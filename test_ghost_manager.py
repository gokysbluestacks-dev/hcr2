"""Regression tests for offline hill-climb cup ghost matchmaking."""

import os
import tempfile
import unittest
import zlib
from unittest.mock import patch

from ghost_manager import GhostManager
from hcr2_proto import get_message_class

Replay = get_message_class("Replay")
Cup = get_message_class("Cup")
FrameData = get_message_class("FrameData")


def make_zipped_frame_data(timestamp=1.0):
    frame_data = FrameData()
    frame_data.frames.add().timeStamp = timestamp
    return zlib.compress(frame_data.SerializeToString())


class GhostManagerHillClimbTests(unittest.TestCase):
    def make_manager(self, available_names):
        manager = GhostManager.__new__(GhostManager)
        manager.authentic_ghosts = {}
        manager.authentic_cups = {}
        manager.player_replays = {}
        manager._player_replay_index = {}
        manager.challenge_replays = {}
        manager._challenge_replay_index = {}
        manager.outbox_replay = None
        manager.hill_climb_sets = list(range(15))
        manager.cup_definitions = {}
        manager.level_ids = {}
        manager._emulator_assets_synced = os.environ.get("HCR2_ALLOW_LOCAL_CUP_CACHE") == "1"
        manager.sync_cups_to_emulator = lambda device="emulator-5554": True

        for set_idx in range(15):
            cup = Cup()
            cup.cupId = "hill_climb_cup"
            cup.replayIds.extend([
                f"cups/ghost_{set_idx}_0.dat",
                f"cups/ghost_{set_idx}_1.dat",
            ])
            cup.ContentVersion = 2
            manager.authentic_cups[f"cup_hill_climb_cup{set_idx}.dat"] = cup
            for track_idx in (0, 1):
                ghost = Replay()
                ghost.playerId = f"ghost-{set_idx}-{track_idx}"
                ghost.available = True
                ghost.vehicle = "jeep"
                ghost.levelId = f"rookie_cup_0{track_idx + 1}_01"
                ghost.zippedFrameData = b"playable ghost frames"
                manager.authentic_ghosts[f"ghost_{set_idx}_{track_idx}.dat"] = ghost


        for name in available_names:
            replay = Replay()
            replay.playerId = name
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = "hill_climb_cup"
            replay.time = 30.0
            replay.zippedFrameData = name.encode()
            manager.authentic_ghosts[name] = replay
        return manager

    def test_matchmaking_never_advertises_packaged_ghosts(self):
        manager = self.make_manager([
            "ghost_0_0.dat", "ghost_0_1.dat",
            "ghost_3_0.dat", "ghost_3_1.dat",
        ])

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 20.0, 7
        )

        self.assertEqual(cups, [])
        self.assertEqual(len(wc_race.Replays), 0)

    def test_matchmaking_returns_three_complete_challenge_only_cups(self):
        manager = self.make_manager([])
        tracks = ["track_a", "track_b"]
        manager.get_track_ids_for_cup = lambda cup_id: tracks
        for player_id in ("owner-a", "owner-b", "owner-c"):
            for level_id, track_name in zip(tracks, ("track-a", "track-b")):
                replay_id = f"challenge-{player_id}-{track_name}"
                replay = Replay()
                replay.playerId = player_id
                replay.available = True
                replay.vehicle = "jeep"
                replay.levelId = level_id
                replay.time = 24.0
                replay._id = replay_id
                replay.zippedFrameData = make_zipped_frame_data()
                manager.register_challenge_replay(replay)

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 20.0, 7
        )

        self.assertEqual(len(cups), 3)
        cup_owners = [
            manager.get_cup_replays(list(cup.replayIds))[0].playerId
            for cup in cups
        ]
        self.assertEqual(len(set(cup_owners)), 3)
        self.assertTrue(all(len(cup.replayIds) == len(tracks) for cup in cups))
        self.assertTrue(all(
            replay_id in manager._challenge_replay_index
            for cup in cups for replay_id in cup.replayIds
        ))
        replay_ids = [replay_id for cup in cups for replay_id in cup.replayIds]
        self.assertTrue(all(
            not replay_id.startswith("cups/ghost_")
            for replay_id in replay_ids
        ))
        first_leg_ids = [cup.replayIds[0] for cup in cups]
        self.assertEqual(
            [replay._id for replay in wc_race.Replays],
            first_leg_ids,
        )
        self.assertEqual(len(wc_race.Replays), len(cups))

    def test_matchmaking_never_mixes_players_across_tracks(self):
        manager = self.make_manager([])
        tracks = ["track_a", "track_b"]
        manager.get_track_ids_for_cup = lambda cup_id: tracks
        for level_id, player_id, replay_id, distance in (
            ("track_a", "player-a", "a-track-a", 400.0),
            ("track_a", "player-b", "b-track-a", 300.0),
            ("track_b", "player-c", "c-track-b", 450.0),
            ("track_b", "player-b", "b-track-b", 300.0),
        ):
            replay = Replay()
            replay.playerId = player_id
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = level_id
            replay.time = 24.0
            replay.distance = distance
            replay._id = replay_id
            replay.zippedFrameData = make_zipped_frame_data()
            manager.register_challenge_replay(replay)

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 20.0, 7
        )

        self.assertEqual(len(cups), 1)
        for cup in cups:
            replays = manager.get_cup_replays(list(cup.replayIds))
            self.assertEqual([replay.playerId for replay in replays], ["player-b", "player-b"])
        self.assertEqual(
            [replay._id for replay in wc_race.Replays],
            [cup.replayIds[0] for cup in cups],
        )

    def test_matchmaking_excludes_requesting_player(self):
        manager = self.make_manager([])
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]
        for level_id, player_id, replay_id in (
            ("track_a", "requester", "requester-track-a"),
            ("track_b", "requester", "requester-track-b"),
            ("track_a", "opponent", "opponent-track-a"),
            ("track_b", "opponent", "opponent-track-b"),
        ):
            replay = Replay()
            replay.playerId = player_id
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = level_id
            replay.time = 24.0
            replay.distance = 100.0
            replay._id = replay_id
            replay.zippedFrameData = make_zipped_frame_data()
            manager.register_challenge_replay(replay)

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup",
            "jeep",
            4.0,
            20.0,
            7,
            requester_player_id="requester",
        )

        self.assertEqual(len(cups), 1)
        for cup in cups:
            replays = manager.get_cup_replays(list(cup.replayIds))
            self.assertEqual([replay.playerId for replay in replays], ["opponent", "opponent"])
        self.assertTrue(all(replay.playerId != "requester" for replay in wc_race.Replays))

    def test_matchmaking_returns_no_cups_without_a_complete_player(self):
        manager = self.make_manager([])
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]
        for level_id, player_id, replay_id in (
            ("track_a", "player-a", "a-track-a"),
            ("track_b", "player-b", "b-track-b"),
        ):
            replay = Replay()
            replay.playerId = player_id
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = level_id
            replay.time = 24.0
            replay._id = replay_id
            replay.zippedFrameData = make_zipped_frame_data()
            manager.register_challenge_replay(replay)

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 20.0, 7
        )

        self.assertEqual(cups, [])
        self.assertEqual(len(wc_race.Replays), 0)

    def test_matchmaking_uses_challenge_replays_when_cup_assets_missing(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        manager.level_ids = {"rookie_cup_01_01.json": "rookie_cup_01_01"}
        manager.cup_definitions = {
            "hill_climb_cup": {"levels": ["rookie_cup_01_01.json"]},
        }
        manager.get_track_ids_for_cup = lambda cup_id: ["rookie_cup_01_01"]
        replay = Replay()
        replay.playerId = "racer"
        replay.available = True
        replay.vehicle = "jeep"
        replay.levelId = "rookie_cup_01_01"
        replay.time = 24.0
        replay.distance = 250.0
        replay._id = "player-run-1"
        replay.zippedFrameData = make_zipped_frame_data()
        manager.register_challenge_replay(replay)

        cups, _ = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 0.0, 7
        )

        self.assertEqual(len(cups), 1)
        self.assertEqual(list(cups[0].replayIds), ["player-run-1"])
        resolved = manager.get_cup_replays(list(cups[0].replayIds))
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].zippedFrameData, make_zipped_frame_data())

    def test_matchmaking_allows_an_opponent_to_switch_vehicles_between_tracks(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]
        # The only owner drives a different vehicle on each leg; a cup lets each
        # leg use its own vehicle, so the opponent is still a valid match.
        for level_id, vehicle, replay_id in (
            ("track_a", "jeep", "jeep-run"),
            ("track_b", "scooter", "scooter-run"),
        ):
            replay = Replay()
            replay.playerId = "player"
            replay.available = True
            replay.vehicle = vehicle
            replay.levelId = level_id
            replay._id = replay_id
            replay.zippedFrameData = make_zipped_frame_data()
            manager.register_challenge_replay(replay)

        cups, _ = manager.create_cup_matchmaking("hill_climb_cup", "jeep", 4.0, 0.0, 7)
        self.assertEqual(len(cups), 1)
        self.assertEqual(list(cups[0].replayIds), ["jeep-run", "scooter-run"])

    def test_matchmaking_does_not_limit_ghosts_to_requesters_vehicle(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]
        for player_id, vehicle in (
            ("jeep-a", "jeep"),
            ("scooter-a", "scooter"),
            ("scooter-b", "scooter"),
            ("scooter-c", "scooter"),
        ):
            for level_id in ("track_a", "track_b"):
                replay = Replay()
                replay.playerId = player_id
                replay.available = True
                replay.vehicle = vehicle
                replay.levelId = level_id
                replay.time = 25.0
                replay.distance = 100.0
                replay._id = f"{player_id}-{level_id}"
                replay.zippedFrameData = make_zipped_frame_data()
                manager.register_challenge_replay(replay)

        cups, _ = manager.create_cup_matchmaking("hill_climb_cup", "jeep", 4.0, 20.0, 7)

        # Requesting "jeep" must not exclude the scooter opponents.
        self.assertEqual(len(cups), 3)
        vehicles = {
            replay.vehicle
            for cup in cups
            for replay in manager.get_cup_replays(list(cup.replayIds))
        }
        self.assertIn("scooter", vehicles)

    def test_matchmaking_scales_ghost_difficulty_with_rank(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]
        for step in range(10):
            ghost_time = 10.0 * (step + 1)
            for level_id in ("track_a", "track_b"):
                replay = Replay()
                replay.playerId = f"ghost-{ghost_time:.0f}"
                replay.available = True
                replay.vehicle = "jeep"
                replay.levelId = level_id
                replay.time = ghost_time
                replay.distance = 100.0
                replay._id = f"ghost-{ghost_time:.0f}-{level_id}"
                replay.zippedFrameData = make_zipped_frame_data()
                manager.register_challenge_replay(replay)

        def selected_times(player_rank):
            cups, _ = manager.create_cup_matchmaking(
                "hill_climb_cup", "jeep", 4.0, player_rank, 7
            )
            return sorted(
                manager.get_cup_replays(list(cup.replayIds))[0].time
                for cup in cups
            )

        bronze_times = selected_times(0.0)
        legendary_times = selected_times(50.0)

        self.assertEqual(len(bronze_times), 3)
        self.assertEqual(len(legendary_times), 3)
        # Training/Bronze I draws from the slowest ghosts, Legendary the fastest.
        self.assertGreaterEqual(min(bronze_times), 50.0)
        self.assertLessEqual(max(legendary_times), 60.0)

    def test_server_cups_folder_ghosts_join_the_cup_pool(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        manager.cup_replays = {}
        manager._cup_replay_index = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a"]

        with tempfile.TemporaryDirectory() as cups_dir:
            replay = Replay()
            replay.playerId = "server-ghost"
            replay.available = True
            replay.vehicle = "jeep"
            replay.levelId = "track_a"
            replay.time = 24.0
            replay.distance = 100.0
            replay.zippedFrameData = make_zipped_frame_data()
            with open(os.path.join(cups_dir, "ghost_3_0.dat"), "wb") as replay_file:
                replay_file.write(replay.SerializeToString())

            with patch("ghost_manager.CUPS_DIR", cups_dir):
                manager._load_server_cup_replays()

        self.assertEqual(
            [replay._id for replay in manager.cup_replays["track_a"]],
            ["cups/ghost_3_0.dat"],
        )
        cups, _ = manager.create_cup_matchmaking("hill_climb_cup", "jeep", 4.0, 0.0, 7)
        self.assertEqual(len(cups), 1)
        self.assertEqual(list(cups[0].replayIds), ["cups/ghost_3_0.dat"])
        resolved = manager.get_cup_replays(list(cups[0].replayIds))
        self.assertEqual(resolved[0].playerId, "server-ghost")

    def test_matchmaking_leads_mixed_cache_and_server_ids_with_a_server_cup(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["track_a", "track_b"]
        manager.cup_replays = {}
        manager._cup_replay_index = {}

        # Server-hosted opponents (no "cups/" prefix) on both tracks.
        for player_id in ("server-a", "server-b"):
            for track in ("track_a", "track_b"):
                replay = Replay()
                replay.playerId = player_id
                replay.available = True
                replay.vehicle = "jeep"
                replay.levelId = track
                replay.time = 24.0
                replay.distance = 100.0
                replay._id = f"more/{player_id}-{track}.dat"
                replay.zippedFrameData = make_zipped_frame_data()
                manager.cup_replays.setdefault(track, []).append(replay)
                manager._cup_replay_index[replay._id] = replay

        # Client-cached opponents ("cups/" prefix) on both tracks.
        for set_idx in range(2):
            for track_idx, track in enumerate(("track_a", "track_b")):
                replay = Replay()
                replay.playerId = f"cache-{set_idx}"
                replay.available = True
                replay.vehicle = "jeep"
                replay.levelId = track
                replay.time = 30.0
                replay.distance = 100.0
                replay._id = f"cups/ghost_{set_idx}_{track_idx}.dat"
                replay.zippedFrameData = make_zipped_frame_data()
                manager.cup_replays.setdefault(track, []).append(replay)
                manager._cup_replay_index[replay._id] = replay

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 0.0, 7
        )

        self.assertEqual(len(cups), 3)
        replay_ids = [rid for cup in cups for rid in cup.replayIds]
        # Both sources are allowed in one response...
        self.assertTrue(any(rid.startswith("cups/") for rid in replay_ids))
        self.assertTrue(any(not rid.startswith("cups/") for rid in replay_ids))
        # ...but the leading cup must be server-hosted so the client fetches the
        # mixed batch online instead of reading it from its local cups/ cache.
        self.assertTrue(all(not rid.startswith("cups/") for rid in cups[0].replayIds))
        self.assertEqual(
            [replay._id for replay in wc_race.Replays],
            [cup.replayIds[0] for cup in cups],
        )

    def test_matchmaking_returns_no_ghost_opponents_when_no_pairs_exist(self):
        manager = self.make_manager(["ghost_2_0.dat"])
        manager.authentic_ghosts["ghost_2_0.dat"].levelId = "unrelated_level"

        cups, wc_race = manager.create_cup_matchmaking(
            "hill_climb_cup", "jeep", 4.0, 20.0, 7
        )

        self.assertEqual(cups, [])
        self.assertEqual(len(wc_race.Replays), 0)

    def test_packaged_ghosts_without_challenge_ids_are_not_matchmaking_candidates(self):
        manager = self.make_manager(["ghost_0_0.dat", "ghost_0_1.dat"])
        manager.authentic_ghosts["ghost_0_0.dat"].levelId = "rookie_cup_01_01"
        manager.authentic_ghosts["ghost_0_1.dat"].levelId = "rookie_cup_02_01"
        manager.authentic_cups = {}
        manager.get_track_ids_for_cup = lambda cup_id: ["rookie_cup_01_01", "rookie_cup_02_01"]

        cups, _ = manager.create_cup_matchmaking("hill_climb_cup", "jeep", 4.0, 0.0, 7)

        self.assertEqual(cups, [])

    def test_track_replay_requests_exclude_metadata_only_uploads(self):
        manager = self.make_manager([])
        manager.authentic_ghosts = {}
        replay = Replay()
        replay.playerId = "racer"
        replay.available = True
        replay.vehicle = "jeep"
        replay.levelId = "rookie_cup_01_01"
        replay._id = "metadata-only"
        manager.player_replays[replay.levelId] = [replay]
        manager._player_replay_index[replay._id] = replay

        self.assertEqual(
            manager.get_replays_for_track(replay.levelId, "jeep", 4.0, 0.0),
            [],
        )

    def test_cup_replay_lookup_preserves_original_replay_metadata(self):
        manager = self.make_manager(["ghost_2_0.dat"])
        original = manager.authentic_ghosts["ghost_2_0.dat"]

        replay = manager.get_cup_replays(["cups/ghost_2_0.dat"])[0]

        self.assertEqual(replay.SerializeToString(), original.SerializeToString())

    def test_cup_replay_keeps_original_recording_even_with_outbox_template(self):
        manager = self.make_manager(["ghost_2_0.dat"])
        source = manager.authentic_ghosts["ghost_2_0.dat"]
        template = Replay()
        template.playerId = "local-player"
        template.levelId = "rookie_cup_01_01"
        template.vehicle = "jeep"
        template.time = 99.0
        template.zippedFrameData = b"local-template-data"
        manager.outbox_replay = template

        served = manager.get_cup_replays(["cups/ghost_2_0.dat"])

        self.assertEqual(len(served), 1)
        self.assertEqual(served[0].SerializeToString(), source.SerializeToString())
        self.assertNotEqual(served[0].zippedFrameData, template.zippedFrameData)

    def test_cup_replay_uses_current_format_frame_data_with_ghost_identity(self):
        manager = self.make_manager(["ghost_2_0.dat", "ghost_2_1.dat"])
        source = manager.authentic_ghosts["ghost_2_0.dat"]
        template = Replay()
        template.playerId = "local-player"
        template.playerName = "local"
        template.levelId = "rookie_cup_01_01"
        template.vehicle = "jeep"
        template.time = 99.0
        template.zippedFrameData = b"current-version-frame-data"
        template.ContentVersion = 7
        manager.outbox_replay = template

        replay_id = "cups/ghost_2_0.dat"
        replay = manager.get_cup_replays([replay_id])[0]
        second_track = manager.get_cup_replays(["cups/ghost_2_1.dat"])[0]

        source = manager.authentic_ghosts["ghost_2_0.dat"]
        self.assertEqual(replay.zippedFrameData, source.zippedFrameData)
        self.assertEqual(replay.ContentVersion, source.ContentVersion)
        self.assertEqual(replay.playerId, source.playerId)
        self.assertEqual(replay.playerName, source.playerName)
        self.assertEqual(replay.levelId, source.levelId)
        self.assertEqual(second_track.levelId, manager.authentic_ghosts["ghost_2_1.dat"].levelId)
        self.assertEqual(replay.vehicle, source.vehicle)
        self.assertEqual(replay.time, source.time)
        self.assertEqual(replay.distance, source.distance)
        self.assertEqual(replay._id, "")

    def test_matchmaking_ignores_authentic_sets_even_when_cache_is_synced(self):
        manager = self.make_manager([
            "ghost_0_0.dat", "ghost_0_1.dat",
            "ghost_1_0.dat", "ghost_1_1.dat",
            "ghost_2_0.dat", "ghost_2_1.dat",
        ])
        manager.authentic_ghosts = {
            name: replay for name, replay in manager.authentic_ghosts.items()
            if name.startswith(("ghost_0_", "ghost_1_", "ghost_2_"))
        }
        manager._emulator_assets_synced = True
        manager.authentic_ghosts["ghost_1_0.dat"].vehicle = "scooter"
        manager.authentic_ghosts["ghost_1_1.dat"].vehicle = "scooter"

        with patch("ghost_manager.random.sample", side_effect=lambda values, count: list(values)[:count]):
            cups, _ = manager.create_cup_matchmaking(
                "hill_climb_cup", "jeep", 4.0, 0.0, 7
            )

        self.assertEqual(cups, [])

    def test_matchmaking_does_not_advertise_uncached_ghost_files(self):
        manager = self.make_manager([
            "ghost_0_0.dat", "ghost_0_1.dat",
            "ghost_1_0.dat", "ghost_1_1.dat",
            "ghost_2_0.dat", "ghost_2_1.dat",
            "ghost_4_0.dat", "ghost_4_1.dat",
        ])
        manager._emulator_assets_synced = True

        with patch("ghost_manager.random.sample", side_effect=lambda values, count: list(values)[:count]):
            cups, _ = manager.create_cup_matchmaking(
                "hill_climb_cup", "jeep", 4.0, 20.0, 7
            )

        self.assertEqual(cups, [])

    def test_matchmaking_treats_same_player_vehicle_variants_as_separate_opponents(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        tracks = ["track_a", "track_b"]
        manager.get_track_ids_for_cup = lambda cup_id: tracks
        # One owner recorded every track with two vehicles: both ghosts must stay
        # usable as distinct opponents, but each cup still holds only one of them.
        for level_id, vehicle in (
            ("track_a", "jeep"),
            ("track_a", "scooter"),
            ("track_b", "jeep"),
            ("track_b", "scooter"),
        ):
            replay = Replay()
            replay.playerId = "multi"
            replay.available = True
            replay.vehicle = vehicle
            replay.levelId = level_id
            replay.time = 24.0
            replay._id = f"multi-{level_id}-{vehicle}"
            replay.zippedFrameData = make_zipped_frame_data()
            manager.register_challenge_replay(replay)

        with patch(
            "ghost_manager.random.sample",
            side_effect=lambda values, count: list(values)[:count],
        ):
            cups, _ = manager.create_cup_matchmaking(
                "hill_climb_cup", "jeep", 4.0, 20.0, 7
            )

        replay_legs = [
            [replay.vehicle for replay in manager.get_cup_replays(list(cup.replayIds))]
            for cup in cups
        ]
        self.assertEqual(len(cups), 2)
        # Each cup keeps a single vehicle across its legs, one variant per cup.
        self.assertEqual(replay_legs, [["jeep", "jeep"], ["scooter", "scooter"]])

    def test_matchmaking_falls_back_when_a_variant_lacks_a_track(self):
        manager = self.make_manager([])
        manager.authentic_cups = {}
        tracks = ["track_a", "track_b"]
        manager.get_track_ids_for_cup = lambda cup_id: tracks
        # "scooter" only exists on the first track; the second leg reuses the
        # owner's jeep ghost so the scooter variant is still raceable.
        for level_id, vehicle in (
            ("track_a", "jeep"),
            ("track_a", "scooter"),
            ("track_b", "jeep"),
        ):
            replay = Replay()
            replay.playerId = "multi"
            replay.available = True
            replay.vehicle = vehicle
            replay.levelId = level_id
            replay.time = 24.0
            replay._id = f"multi-{level_id}-{vehicle}"
            replay.zippedFrameData = make_zipped_frame_data()
            manager.register_challenge_replay(replay)

        with patch(
            "ghost_manager.random.sample",
            side_effect=lambda values, count: list(values)[:count],
        ):
            cups, _ = manager.create_cup_matchmaking(
                "hill_climb_cup", "jeep", 4.0, 20.0, 7
            )

        leg_ids = sorted(list(cup.replayIds) for cup in cups)
        self.assertEqual(len(cups), 2)
        self.assertEqual(
            leg_ids,
            sorted([
                ["multi-track_a-jeep", "multi-track_b-jeep"],
                ["multi-track_a-scooter", "multi-track_b-jeep"],
            ]),
        )


if __name__ == "__main__":
    unittest.main()
