import tempfile
import unittest
from unittest.mock import patch

from handlers import MessageDispatcher
from hcr2_proto import get_message_class

FSMessage = get_message_class("FSMessage")
Replay = get_message_class("Replay")


class ChallengeHandlerTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = MessageDispatcher(0x123456)
        self.dispatcher.player_id = "ChallengeTestPlayer"

    def test_request_returns_challenge_from_saved_authentic_replay(self):
        replay = Replay()
        replay.playerId = "OpponentPlayer"
        replay.playerName = "Local Challenger"
        replay.levelId = "rookie_cup_01_01"
        replay.vehicle = "jeep"
        replay.available = True
        replay.time = 27.5
        replay.distance = 140.0
        replay.finishingStatus = 0
        replay.zippedFrameData = b"authentic-frame-payload"

        request = FSMessage()
        request.MessageType = 29
        request.MessageNumber = 73

        with patch("handlers.ghost_mgr.player_replays", {"rookie_cup_01_01": [replay]}), patch(
            "handlers.PlayerDB.iter_players", return_value=[]
        ):
            response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 29)
        self.assertEqual(response.MessageNumber, 73)
        self.assertEqual(response.ResponseCode, 0)
        self.assertEqual(len(response.Challenges), 1)
        challenge = response.Challenges[0]
        self.assertTrue(challenge.challengeId)
        self.assertGreater(challenge.expirationTimeStamp, 0)
        self.assertEqual(challenge.challengerReplay.playerId, "OpponentPlayer")
        self.assertEqual(challenge.challengerReplay.zippedFrameData, b"authentic-frame-payload")
        self.assertEqual(challenge.vehicleStatus.vehicleId, "jeep")
        self.assertEqual(challenge.totalTries, 0)
        self.assertEqual(challenge.totalWins, 0)
        self.assertEqual(challenge.totalLosses, 0)

    def test_create_challenge_request_with_challenge_payload(self):
        request = FSMessage()
        request.MessageType = 27
        request.MessageNumber = 76
        request.Challenge.challengerReplay.playerId = "ChallengeTestPlayer"
        request.Challenge.challengerReplay.levelId = "rookie_cup_01_01"
        request.Challenge.challengerReplay.vehicle = "jeep"
        request.Challenge.challengerReplay.available = True
        request.Challenge.challengerReplay.zippedFrameData = b"replay-frames"
        request.Challenge.vehicleStatus.vehicleId = "jeep"

        response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 27)
        self.assertEqual(response.MessageNumber, 76)
        self.assertEqual(response.ResponseCode, 1)
        self.assertTrue(response.ChallengeId)

    def test_created_challenge_replay_is_saved_and_offered_to_other_players(self):
        request = FSMessage()
        request.MessageType = 27
        request.MessageNumber = 80
        request.Challenge.challengerReplay.playerId = "ChallengeTestPlayer"
        request.Challenge.challengerReplay.playerName = "Challenge Racer"
        request.Challenge.challengerReplay.levelId = "rookie_cup_02_01"
        request.Challenge.challengerReplay.vehicle = "superjeep"
        request.Challenge.challengerReplay.available = True
        request.Challenge.challengerReplay.zippedFrameData = b"time-trial-frame-data"
        request.Challenge.vehicleStatus.vehicleId = "superjeep"

        with tempfile.TemporaryDirectory() as data_dir, patch("db.DATA_DIR", data_dir), patch(
            "handlers.ghost_mgr.player_replays", {}
        ), patch("handlers.ghost_mgr._player_replay_index", {}), patch(
            "handlers.ghost_mgr.challenge_replays", {}
        ), patch("handlers.ghost_mgr._challenge_replay_index", {}):
            response = self.dispatcher.handle(request)[0]
            self.assertEqual(response.ResponseCode, 1)
            challenge_id = response.ChallengeId
            self.assertTrue(challenge_id)

            from db import PlayerDB
            saved_profile = PlayerDB.load_player(self.dispatcher.player_id)
            stored = saved_profile["created_challenges"][challenge_id]
            self.assertEqual(stored["level_id"], "rookie_cup_02_01")
            self.assertEqual(stored["vehicle_id"], "superjeep")

            other = MessageDispatcher(0x654321)
            other.player_id = "OtherPlayer"
            request_list = FSMessage()
            request_list.MessageType = 29
            request_list.ChallengeIds.append(challenge_id)
            offered = other.handle(request_list)[0]
            self.assertEqual(len(offered.Challenges), 1)
            self.assertEqual(offered.Challenges[0].challengeId, challenge_id)
            self.assertEqual(
                offered.Challenges[0].challengerReplay.zippedFrameData,
                b"time-trial-frame-data",
            )
            self.assertEqual(offered.Challenges[0].vehicleStatus.vehicleId, "superjeep")

    def test_create_challenge_with_empty_frame_data_is_rejected(self):
        request = FSMessage()
        request.MessageType = 27
        request.MessageNumber = 78
        request.Challenge.challengerReplay.playerId = "ChallengeTestPlayer"
        request.Challenge.challengerReplay.levelId = "rookie_cup_01_01"
        request.Challenge.challengerReplay.vehicle = "jeep"
        request.Challenge.challengerReplay.available = True
        request.Challenge.vehicleStatus.vehicleId = "jeep"

        response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.ResponseCode, 0)

    def test_create_challenge_without_payload_is_rejected(self):
        request = FSMessage()
        request.MessageType = 27
        request.MessageNumber = 77

        response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 27)
        self.assertEqual(response.MessageNumber, 77)
        self.assertEqual(response.ResponseCode, 0)

    def test_update_challenge_is_acknowledged(self):
        request = FSMessage()
        request.MessageType = 28
        request.MessageNumber = 75
        request.ChallengeId = "challenge-123"
        request.Replay.playerId = "ChallengeTestPlayer"
        request.Replay.levelId = "rookie_cup_01_01"
        request.Replay.vehicle = "jeep"
        request.Replay.available = True
        request.Replay.zippedFrameData = b"replay-update"

        response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 28)
        self.assertEqual(response.MessageNumber, 75)
        self.assertEqual(response.ResponseCode, 0)
        self.assertEqual(response.Session, self.dispatcher.session_id)

    def test_request_returns_empty_collection_when_no_replay_exists(self):
        request = FSMessage()
        request.MessageType = 29
        request.MessageNumber = 74

        with patch("handlers.ghost_mgr.player_replays", {}), patch(
            "handlers.PlayerDB.iter_players", return_value=[]
        ):
            response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 29)
        self.assertEqual(response.MessageNumber, 74)
        self.assertEqual(response.ResponseCode, 0)
        self.assertEqual(len(response.Challenges), 0)


if __name__ == "__main__":
    unittest.main()
