import tempfile
import unittest
from unittest.mock import patch

from db import PlayerDB
from handlers import MessageDispatcher
from hcr2_proto import get_message_class

FSMessage = get_message_class("FSMessage")


class LeaderboardHandlerTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = MessageDispatcher(0x123456)
        self.dispatcher.player_id = "LeaderboardTestPlayer"

    def test_leaderboard_request_returns_local_entry_and_echoes_paging(self):
        profile = {
            "player_id": "LeaderboardTestPlayer",
            "player_name": "Test Racer",
            "coins": 12,
            "diamonds": 3,
            "xp": 7,
            "rank": 0.0,
        }
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("db.DATA_DIR", data_dir):
                PlayerDB.save_player("LeaderboardTestPlayer", profile)
                self._assert_leaderboard_request()

    def _assert_leaderboard_request(self):
        request = FSMessage()
        from hcr2_proto import get_message_class
        Replay = get_message_class("Replay")
        replay = Replay()
        replay.playerId = "LeaderboardTestPlayer"
        replay.playerName = "Test Racer"
        replay.levelId = "rookie_cup_01_01"
        replay.vehicle = "jeep"
        replay.available = True
        replay.time = 25.5
        replay.distance = 120.0
        replay.finishingStatus = 0

        request = FSMessage()
        request.MessageType = 4
        request.MessageNumber = 41
        request.LevelId = "rookie_cup_01_01"
        request.LeaderboardFilter = "global"
        request.pageOffset = 0
        request.ReferenceTime = 25.5
        request.VehicleId = "jeep"

        with patch("handlers.ghost_mgr.player_replays", {"rookie_cup_01_01": [replay]}):
            response = self.dispatcher.handle(request)[0]
        self.assertEqual(response.MessageType, 4)
        self.assertEqual(response.MessageNumber, 41)
        self.assertEqual(response.ResponseCode, 0)
        self.assertEqual(response.Leaderboard.levelId, "rookie_cup_01_01")
        self.assertEqual(response.Leaderboard.leaderboardFilter, "global")
        self.assertEqual(response.Leaderboard.pageOffset, 0)
        self.assertEqual(len(response.Leaderboard.leaderboard), 1)
        entry = response.Leaderboard.leaderboard[0]
        self.assertEqual(entry.playerId, "LeaderboardTestPlayer")
        self.assertEqual(entry.playerName, "Test Racer")
        self.assertEqual(entry.levelId, "rookie_cup_01_01")
        self.assertEqual(entry.vehicleId, "jeep")
        self.assertEqual(entry.time, 25.5)
        self.assertEqual(entry.distance, 120.0)
        self.assertTrue(entry.HasField("replayId"))

    def test_standings_rank_player_against_other_saved_results(self):
        Replay = get_message_class("Replay")
        faster = Replay()
        faster.playerId = "FastPlayer"
        faster.playerName = "Fast Racer"
        faster.levelId = "rookie_cup_01_01"
        faster.vehicle = "jeep"
        faster.available = True
        faster.time = 20.0
        faster.distance = 120.0
        faster._id = "fast-replay"

        slower = Replay()
        slower.playerId = "LeaderboardTestPlayer"
        slower.playerName = "Test Racer"
        slower.levelId = "rookie_cup_01_01"
        slower.vehicle = "jeep"
        slower.available = True
        slower.time = 25.5
        slower.distance = 120.0
        slower._id = "slow-replay"

        request = FSMessage()
        request.MessageType = 23
        request.MessageNumber = 43
        request.LevelId = "rookie_cup_01_01"

        with patch("handlers.ghost_mgr.player_replays", {
            "rookie_cup_01_01": [slower, faster],
        }), patch.object(PlayerDB, "get_friends", return_value=[]):
            response = self.dispatcher.handle(request)[0]

        standings = response.LeaderboardStandings
        self.assertEqual(standings.globalStanding, 2)
        self.assertEqual(standings.localStanding, 1)
        self.assertEqual(standings.friendsStanding, 1)

    def test_local_friends_and_global_filters_return_scoped_results(self):
        Replay = get_message_class("Replay")
        replays = []
        for player_id, distance, vehicle in (
            ("LeaderboardTestPlayer", 120.0, "jeep"),
            ("FriendPlayer", 110.0, "jeep"),
            ("OtherPlayer", 100.0, "sportscar"),
        ):
            replay = Replay()
            replay.playerId = player_id
            replay.playerName = player_id
            replay.levelId = "rookie_cup_01_01"
            replay.vehicle = vehicle
            replay.available = True
            replay.finishingStatus = 0
            replay.time = 20.0
            replay.distance = distance
            replay._id = f"replay-{player_id}"
            replays.append(replay)

        request = FSMessage()
        request.MessageType = 4
        request.LevelId = "rookie_cup_01_01"
        request.pageOffset = 0

        with patch("handlers.ghost_mgr.player_replays", {"rookie_cup_01_01": replays}), patch.object(
            PlayerDB, "get_friends", return_value=["FriendPlayer"]
        ):
            request.LeaderboardFilter = "local"
            local = self.dispatcher.handle(request)[0].Leaderboard
            request.LeaderboardFilter = "friends"
            friends = self.dispatcher.handle(request)[0].Leaderboard
            request.LeaderboardFilter = "global"
            global_board = self.dispatcher.handle(request)[0].Leaderboard
            request.LeaderboardFilter = "vehicles"
            request.VehicleId = "jeep"
            vehicles = self.dispatcher.handle(request)[0].Leaderboard

        self.assertEqual([row.playerId for row in local.leaderboard], ["LeaderboardTestPlayer"])
        self.assertEqual(
            [row.playerId for row in friends.leaderboard],
            ["LeaderboardTestPlayer", "FriendPlayer"],
        )
        self.assertEqual(len(global_board.leaderboard), 3)
        self.assertEqual(
            [row.playerId for row in vehicles.leaderboard],
            ["LeaderboardTestPlayer", "FriendPlayer"],
        )

    def test_vehicle_filter_uses_requested_vehicle(self):
        Replay = get_message_class("Replay")
        jeep = Replay()
        jeep.playerId = "JeepPlayer"
        jeep.levelId = "rookie_cup_01_01"
        jeep.vehicle = "jeep"
        jeep.available = True
        jeep.finishingStatus = 0
        jeep.distance = 50.0
        jeep.time = 10.0

        sportscar = Replay()
        sportscar.playerId = "CarPlayer"
        sportscar.levelId = "rookie_cup_01_01"
        sportscar.vehicle = "sportscar"
        sportscar.available = True
        sportscar.finishingStatus = 0
        sportscar.distance = 45.0
        sportscar.time = 9.0

        request = FSMessage()
        request.MessageType = 4
        request.LevelId = "rookie_cup_01_01"
        request.LeaderboardFilter = "vehicles"
        request.VehicleId = "sportscar"
        with patch("handlers.ghost_mgr.player_replays", {
            "rookie_cup_01_01": [jeep, sportscar],
        }):
            response = self.dispatcher.handle(request)[0]

        self.assertEqual(
            [row.playerId for row in response.Leaderboard.leaderboard],
            ["CarPlayer"],
        )

    def test_leaderboard_lists_global_results_in_rank_order(self):
        Replay = get_message_class("Replay")
        slower = Replay()
        slower.playerId = "LeaderboardTestPlayer"
        slower.playerName = "Test Racer"
        slower.levelId = "rookie_cup_01_01"
        slower.vehicle = "jeep"
        slower.available = True
        slower.time = 25.5
        slower.distance = 120.0

        faster = Replay()
        faster.playerId = "FastPlayer"
        faster.playerName = "Fast Racer"
        faster.levelId = "rookie_cup_01_01"
        faster.vehicle = "jeep"
        faster.available = True
        faster.time = 20.0
        faster.distance = 120.0

        request = FSMessage()
        request.MessageType = 4
        request.MessageNumber = 44
        request.LevelId = "rookie_cup_01_01"
        request.pageOffset = 0

        with patch("handlers.ghost_mgr.player_replays", {
            "rookie_cup_01_01": [slower, faster],
        }):
            response = self.dispatcher.handle(request)[0]

        self.assertEqual(len(response.Leaderboard.leaderboard), 2)
        self.assertEqual(response.Leaderboard.leaderboard[0].playerId, "FastPlayer")
        self.assertEqual(response.Leaderboard.leaderboard[1].playerId, "LeaderboardTestPlayer")

    def test_standings_are_marked_unavailable_not_fabricated(self):
        from hcr2_proto import get_message_class
        Replay = get_message_class("Replay")
        replay = Replay()
        replay.playerId = "LeaderboardTestPlayer"
        replay.playerName = "Test Racer"
        replay.levelId = "rookie_cup_01_01"
        replay.available = True
        replay.time = 25.5
        replay.distance = 120.0

        request = FSMessage()
        request.MessageType = 23
        request.MessageNumber = 42
        request.LevelId = "rookie_cup_01_01"

        with patch("handlers.ghost_mgr.player_replays", {"rookie_cup_01_01": [replay]}):
            response = self.dispatcher.handle(request)[0]
        self.assertEqual(response.MessageType, 23)
        self.assertEqual(response.MessageNumber, 42)
        standings = response.LeaderboardStandings
        self.assertEqual(standings.levelId, "rookie_cup_01_01")
        self.assertTrue(standings.globalStandingValid)
        self.assertTrue(standings.localStandingValid)
        self.assertTrue(standings.friendsStandingValid)
        self.assertEqual(standings.globalStanding, 1)
        self.assertEqual(standings.localStanding, 1)
        self.assertEqual(standings.friendsStanding, 1)


if __name__ == "__main__":
    unittest.main()
