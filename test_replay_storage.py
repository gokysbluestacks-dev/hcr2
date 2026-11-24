"""Tests for preserving replay frame payloads received from the client."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ghost_manager import GhostManager
from handlers import MessageDispatcher
from hcr2_proto import get_message_class

FSMessage = get_message_class("FSMessage")
Replay = get_message_class("Replay")


class ReplayStorageTests(unittest.TestCase):
    def test_store_replay_preserves_compressed_and_structured_frame_data(self):
        with tempfile.TemporaryDirectory() as data_dir:
            manager = GhostManager.__new__(GhostManager)
            manager.authentic_ghosts = {}
            manager.authentic_cups = {}
            manager.player_replays = {}
            manager._player_replay_index = {}
            manager.outbox_replay = None

            replay = Replay()
            replay.playerId = "TestPlayer"
            replay.playerName = "Test Driver"
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = "rookie_cup_01_01"
            replay.time = 24.5
            replay.distance = 321.0
            replay.zippedFrameData = b"compressed-time-trial-frames"
            replay.frameData.frames.add().timeStamp = 1.25
            replay.frames.add().timeStamp = 2.5

            request = FSMessage()
            request.MessageType = 2
            request.MessageNumber = 9
            request.PlayerId = "TestPlayer"
            request.Replay.CopyFrom(replay)
            dispatcher = MessageDispatcher(12345)
            dispatcher.player_id = "TestPlayer"

            replay_dir = os.path.join(data_dir, "replays")
            os.makedirs(replay_dir, exist_ok=True)
            with patch("ghost_manager.REPLAYS_DIR", replay_dir), patch(
                "handlers.ghost_mgr", manager
            ):
                response = dispatcher.handle(request)[0]
                stored_path = os.path.join(data_dir, "replays", response.Key + ".dat")
                self.assertTrue(os.path.isfile(stored_path))
                with open(stored_path, "rb") as replay_file:
                    stored = Replay()
                    stored.ParseFromString(replay_file.read())

            self.assertEqual(stored.zippedFrameData, replay.zippedFrameData)
            self.assertEqual(stored.frameData.SerializeToString(), replay.frameData.SerializeToString())
            self.assertEqual(stored.frames[0].timeStamp, replay.frames[0].timeStamp)
            self.assertEqual(stored.distance, 321.0)
            self.assertEqual(stored.time, 24.5)
            self.assertEqual(stored._id, response.Key)
            self.assertEqual(
                manager._player_replay_index[response.Key].zippedFrameData,
                replay.zippedFrameData,
            )


if __name__ == "__main__":
    unittest.main()
