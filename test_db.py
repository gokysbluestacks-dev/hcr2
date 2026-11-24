"""Tests for persisted profile values and explicit protobuf zeroes."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from db import PlayerDB
from hcr2_proto import get_message_class

GameStatus = get_message_class("GameStatus")


class PlayerDBTests(unittest.TestCase):
    def test_new_profile_uses_unadvanced_values(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("db.DATA_DIR", data_dir):
                profile = PlayerDB.load_player("new-player")
                self.assertEqual(profile["coins"], 0)
                self.assertEqual(profile["diamonds"], 0)
                self.assertEqual(profile["xp"], 0)
                self.assertEqual(profile["rank"], 0.0)
                self.assertEqual(profile["vehicles"], ["jeep"])
                self.assertEqual(profile["worlds"], ["countryside_01"])

    def test_explicit_zero_rank_and_progress_overwrite_stale_profile(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with patch("db.DATA_DIR", data_dir):
                PlayerDB.save_player("player", {
                    "player_id": "player",
                    "coins": 800,
                    "diamonds": 70,
                    "xp": 100,
                    "rank": 20.0,
                    "vehicles": ["jeep", "monowheel"],
                    "worlds": ["countryside_01", "desert_01"],
                })
                status = GameStatus()
                status.totalCoinsCollected = 23
                status.diamonds = 64
                status.playerXp = 318
                status.WCRank = 0.0
                status.unlockedVehicles.append("jeep")
                status.ownedWorlds.append("countryside_01")

                saved = PlayerDB.update_from_game_status("player", status)
                self.assertEqual(saved["coins"], 23)
                self.assertEqual(saved["diamonds"], 64)
                self.assertEqual(saved["xp"], 318)
                self.assertEqual(saved["rank"], 0.0)
                self.assertEqual(saved["vehicles"], ["jeep"])
                self.assertEqual(saved["worlds"], ["countryside_01"])

                with open(os.path.join(data_dir, "player.json"), encoding="utf-8") as f:
                    self.assertEqual(json.load(f)["rank"], 0.0)


if __name__ == "__main__":
    unittest.main()
