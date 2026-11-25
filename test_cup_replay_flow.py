"""Integration tests for replay-ID lookup in generated cup opponents."""

import os
import tempfile
import unittest
import zlib
from unittest.mock import patch

from ghost_manager import GhostManager
from handlers import MessageDispatcher
from hcr2_proto import get_message_class

FSMessage = get_message_class("FSMessage")
Replay = get_message_class("Replay")
FrameData = get_message_class("FrameData")


def make_zipped_frame_data(timestamp=1.0):
    frame_data = FrameData()
    frame_data.frames.add().timeStamp = timestamp
    raw_payload = frame_data.SerializeToString()
    return raw_payload, zlib.compress(raw_payload)


class CupReplayFlowTests(unittest.TestCase):
    def test_create_cup_message_is_acknowledged_as_cup_result(self):
        request = FSMessage()
        request.MessageType = 30
        request.MessageNumber = 18
        cup = request.Cups.add()
        cup.cupId = "hill_climb_cup"
        cup.replayIds.extend(["more/1/track_a_jeep.dat"])
        request.FinishPosition = 1

        dispatcher = MessageDispatcher(1234)
        response = dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 30)
        self.assertEqual(response.ResponseCode, 0)
        self.assertEqual(response.Session, 1234)
        self.assertEqual(response.MessageNumber, 18)
        self.assertFalse(response.HasField("Key"))

    def test_local_cup_replays_load_and_serve_from_more_directory(self):
        manager = GhostManager.__new__(GhostManager)
        manager.cup_replays = {}
        manager._cup_replay_index = {}
        manager.challenge_replays = {}
        manager._challenge_replay_index = {}
        manager.player_replays = {}
        manager._player_replay_index = {}
        manager.authentic_ghosts = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]

        raw_frame_data_by_id = {}
        with tempfile.TemporaryDirectory() as replay_dir:
            for level_id in ("track_a", "track_b"):
                replay = Replay()
                replay.playerId = "local-opponent"
                replay.available = True
                replay.vehicle = "jeep"
                replay.levelId = level_id
                replay.time = 25.0
                replay.distance = 100.0
                raw_frame_data, replay.zippedFrameData = make_zipped_frame_data()
                filename = f"{level_id}_jeep.dat"
                path = os.path.join(replay_dir, "1", filename)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as replay_file:
                    replay_file.write(replay.SerializeToString())
                raw_frame_data_by_id[f"more/1/{filename}"] = raw_frame_data

            with patch("ghost_manager.CUP_REPLAYS_DIR", replay_dir):
                manager._load_local_cup_replays()

        for level_id in ("track_a", "track_b"):
            challenge_replay = Replay()
            challenge_replay.playerId = "uploaded-opponent"
            challenge_replay.available = True
            challenge_replay.vehicle = "jeep"
            challenge_replay.levelId = level_id
            challenge_replay.time = 20.0
            challenge_replay.distance = 10000.0
            challenge_replay._id = f"uploaded-{level_id}"
            challenge_raw_frame_data, challenge_replay.zippedFrameData = make_zipped_frame_data(2.0)
            raw_frame_data_by_id[challenge_replay._id] = challenge_raw_frame_data
            manager.register_challenge_replay(challenge_replay)

        cups, inline_wcrace = manager.create_cup_matchmaking(
            "local_cup", "jeep", 4.0, 0.0, 7
        )

        local_ids = ["more/1/track_a_jeep.dat", "more/1/track_b_jeep.dat"]
        uploaded_ids = ["uploaded-track_a", "uploaded-track_b"]
        valid_owner_replays = [local_ids, uploaded_ids]
        self.assertEqual(len(cups), 2)
        # The same-vehicle slot now chooses randomly among its best candidates,
        # so any valid owner set is acceptable.
        for cup in cups:
            self.assertIn(list(cup.replayIds), valid_owner_replays)
        first_leg_ids = [cup.replayIds[0] for cup in cups]
        self.assertEqual([r._id for r in inline_wcrace.Replays], first_leg_ids)
        self.assertEqual(
            [r.byteFrameData for r in inline_wcrace.Replays],
            [raw_frame_data_by_id[replay_id] for replay_id in first_leg_ids],
        )
        self.assertEqual(
            [r.ContentVersion for r in inline_wcrace.Replays],
            [7] * len(inline_wcrace.Replays),
        )
        self.assertEqual(
            [r._id for r in manager.get_cup_replays(local_ids)],
            local_ids,
        )

    def test_challenge_cup_ids_return_replays_through_both_request_paths(self):
        manager = GhostManager.__new__(GhostManager)
        manager.authentic_ghosts = {}
        manager.authentic_cups = {}
        manager.player_replays = {}
        manager._player_replay_index = {}
        manager.challenge_replays = {}
        manager._challenge_replay_index = {}
        manager.hill_climb_sets = []
        manager.cup_definitions = {}
        manager.level_ids = {}
        manager._emulator_assets_synced = False
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]

        raw_frame_data_by_id = {}
        for level_id, replay_id in (("track_a", "run-track-a"), ("track_b", "run-track-b")):
            replay = Replay()
            replay.playerId = "player"
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = level_id
            replay.time = 25.0
            replay.distance = 100.0
            replay._id = "challenge-" + replay_id
            raw_frame_data, replay.zippedFrameData = make_zipped_frame_data()
            raw_frame_data_by_id[replay._id] = raw_frame_data
            manager.register_challenge_replay(replay)

        for level_id, replay_id in (
            ("track_a", "opponent-track-a"),
            ("track_b", "opponent-track-b"),
        ):
            replay = Replay()
            replay.playerId = "opponent"
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = level_id
            replay.time = 30.0
            replay.distance = 50.0
            replay._id = replay_id
            raw_frame_data, replay.zippedFrameData = make_zipped_frame_data(2.0)
            raw_frame_data_by_id[replay_id] = raw_frame_data
            manager.register_challenge_replay(replay)

        cups, inline_wcrace = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 0.0, 7
        )
        self.assertEqual(len(cups), 2)
        valid_owner_replays = [
            ["challenge-run-track-a", "challenge-run-track-b"],
            ["opponent-track-a", "opponent-track-b"],
        ]
        for cup in cups:
            self.assertIn(list(cup.replayIds), valid_owner_replays)
        first_leg_ids = [cup.replayIds[0] for cup in cups]
        self.assertEqual([replay._id for replay in inline_wcrace.Replays], first_leg_ids)

        cup_request = FSMessage()
        cup_request.MessageType = 31
        cup_request.MessageNumber = 5
        cup_request.CupId = "hill_climb_cup"
        cup_request.VehicleId = "jeep"
        cup_request.PValue = 4.0
        cup_request.ContentVersion = 7
        dispatcher = MessageDispatcher(1234)
        dispatcher.player_id = "player"
        with patch("handlers.ghost_mgr", manager), patch(
            "handlers.PlayerDB.load_player", return_value={"rank": 0.0}
        ):
            cup_response = dispatcher.handle(cup_request)[0]
        self.assertTrue(cup_response.SendCupReplays)
        self.assertEqual(
            [replay._id for replay in cup_response.WCRace.Replays],
            [cup.replayIds[0] for cup in cup_response.Cups],
        )
        self.assertEqual(
            [replay.byteFrameData for replay in cup_response.WCRace.Replays],
            [raw_frame_data_by_id[replay._id] for replay in cup_response.WCRace.Replays],
        )
        self.assertTrue(all(
            replay.HasField("ContentVersion") and replay.ContentVersion == 7
            for replay in cup_response.WCRace.Replays
        ))
        self.assertTrue(all(not replay.zippedFrameData for replay in cup_response.WCRace.Replays))
        self.assertEqual(len(cup_response.Cups), 1)
        self.assertEqual(len(cup_response.WCRace.Replays), 1)
        self.assertTrue(all(
            replay.playerId == "opponent"
            for replay in cup_response.WCRace.Replays
        ))

        request = FSMessage()
        request.MessageType = 21
        request.MessageNumber = 6
        request.LevelId = "track_b"
        request.VehicleId = "jeep"
        request.ReplayIds.append(cup_response.Cups[0].replayIds[1])
        dispatcher = MessageDispatcher(1234)
        dispatcher.player_id = "player"
        with patch("handlers.ghost_mgr", manager):
            wc_response = dispatcher.handle(request)[0]

        self.assertEqual(len(wc_response.WCRace.Replays), 1)
        self.assertEqual(
            [replay.byteFrameData for replay in wc_response.WCRace.Replays],
            [raw_frame_data_by_id[cup_response.Cups[0].replayIds[1]]],
        )
        self.assertEqual(wc_response.WCRace.Replays[0].ContentVersion, 7)

        request.MessageType = 6
        request.ReplayIds[:] = list(cups[0].replayIds)
        with patch("handlers.ghost_mgr", manager):
            replay_response = dispatcher.handle(request)[0]
        self.assertEqual(len(replay_response.Replays), 2)
        self.assertEqual(
            [replay.byteFrameData for replay in replay_response.Replays],
            [raw_frame_data_by_id[replay_id] for replay_id in cups[0].replayIds],
        )

    def test_invalid_compressed_frames_are_not_offered_for_cups(self):
        manager = GhostManager.__new__(GhostManager)
        manager.authentic_ghosts = {}
        manager.authentic_cups = {}
        manager.player_replays = {}
        manager._player_replay_index = {}
        manager.challenge_replays = {}
        manager._challenge_replay_index = {}
        manager.hill_climb_sets = []
        manager.cup_definitions = {}
        manager.level_ids = {}
        manager._emulator_assets_synced = False
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a"]

        replay = Replay()
        replay.playerId = "opponent"
        replay.available = True
        replay.vehicle = "jeep"
        replay.levelId = "track_a"
        replay._id = "bad-frame-stream"
        replay.zippedFrameData = b"not a zlib FrameData stream"
        manager.register_challenge_replay(replay)

        cups, inline_wcrace = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 0.0, 7
        )

        self.assertEqual(cups, [])
        self.assertEqual(len(inline_wcrace.Replays), 0)

    def test_cup_ghosts_load_from_persisted_challenge_replays(self):
        challenge_replay = Replay()
        challenge_replay.playerId = "challenge-owner"
        challenge_replay.available = True
        challenge_replay.vehicle = "jeep"
        challenge_replay.time = 24.0
        challenge_replay.levelId = "track_a"
        challenge_replay._id = "challenge-cup-run"
        raw_frame_data, challenge_replay.zippedFrameData = make_zipped_frame_data()
        profile = {
            "created_challenges": {
                "challenge-cup-run": {
                    "challenge_id": "challenge-cup-run",
                    "replay": challenge_replay.SerializeToString().hex(),
                }
            }
        }

        with patch.object(GhostManager, "_load_level_ids"), patch.object(
            GhostManager, "_load_events_rank"
        ), patch.object(GhostManager, "_load_authentic_ghosts"), patch.object(
            GhostManager, "_load_authentic_cups"
        ), patch.object(GhostManager, "_load_saved_player_replays"), patch(
            "ghost_manager.PlayerDB.iter_players",
            return_value=[("challenge-owner", profile)],
        ):
            manager = GhostManager()

        manager.get_track_ids_for_cup = lambda cup_id: ["track_a"]
        cups, _ = manager.create_cup_matchmaking("challenge_cup", "jeep", 4.0, 0.0, 7)

        self.assertEqual(len(cups), 1)
        self.assertTrue(all(
            list(cup.replayIds) == ["challenge-cup-run"] for cup in cups
        ))
        served = manager.get_cup_replays(list(cups[0].replayIds))
        self.assertEqual(len(served), 1)
        self.assertEqual(served[0].zippedFrameData, challenge_replay.zippedFrameData)

        request = FSMessage()
        request.MessageType = 21
        request.MessageNumber = 91
        request.LevelId = "track_a"
        request.VehicleId = "jeep"
        request.ReplayIds.extend(cups[0].replayIds)
        dispatcher = MessageDispatcher(1234)
        dispatcher.player_id = "cup-player"
        with patch("handlers.ghost_mgr", manager), patch(
            "handlers.PlayerDB.load_player", return_value={"rank": 0.0}
        ):
            response = dispatcher.handle(request)[0]

        self.assertEqual(len(response.WCRace.Replays), 1)
        self.assertEqual(response.WCRace.Replays[0].byteFrameData, raw_frame_data)
        self.assertFalse(response.WCRace.Replays[0].zippedFrameData)


if __name__ == "__main__":
    unittest.main()
