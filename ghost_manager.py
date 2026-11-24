"""
Hill Climb Racing 2 - Ghost & Replay Manager
Handles authentic ghost loading, matchmaking generation, dynamic replay synthesis,
and player replay persistence.
"""

import glob
import json
import logging
import os
import random
import subprocess
import time
import zlib
from typing import List, Tuple, Optional
from google.protobuf.message import DecodeError
from db import PlayerDB
from hcr2_proto import get_message_class

ReplayCls = get_message_class("Replay")
FrameDataCls = get_message_class("FrameData")
CupCls = get_message_class("Cup")
WCRaceCls = get_message_class("WCRace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APK_CUPS_DIR = os.path.expanduser(os.environ.get(
    "HCR2_CUPS_DIR", os.path.join(os.path.expanduser("~"), "apk", "assets", "Common", "cups")
))
OUTBOX_TEMPLATE = "rookie_cup_01_01_jeep.dat"
DECRYPTED_DIR = os.path.expanduser(os.environ.get(
    "HCR2_DECRYPTED_DIR", os.path.join(os.path.expanduser("~"), "decrypted_output")
))
DATA_DIR = os.path.expanduser(os.environ.get(
    "HCR2_DATA_DIR", os.path.join(BASE_DIR, "player_data")
))
REPLAYS_DIR = os.path.join(DATA_DIR, "replays")
CUP_REPLAYS_DIR = os.path.join(BASE_DIR, "more")
ADB_PATH = os.environ.get("HCR2_ADB_PATH", "")
ANDROID_CUPS_DIR = "/data/data/com.fingersoft.hcr2/files/cups"

os.makedirs(REPLAYS_DIR, exist_ok=True)
LOGGER = logging.getLogger("hcr2.ghosts")

class GhostManager:
    def __init__(self, sync_emulator: bool = False):
        self.authentic_ghosts = {}  # filename -> Replay protobuf
        self.authentic_cups = {}    # filename -> Cup protobuf
        self.player_replays = {}    # level_id -> list of Replay protobufs
        self._player_replay_index = {}  # replay ID -> Replay protobuf
        self.challenge_replays = {}  # level_id -> explicitly created challenge replays
        self._challenge_replay_index = {}  # challenge ID -> Replay protobuf
        self.cup_replays = {}  # level_id -> packaged cup replays
        self._cup_replay_index = {}  # packaged cup replay ID -> Replay protobuf
        self.outbox_replay = None

        self.hill_climb_sets = list(range(15))  # Known offline sets; filtered against loaded assets at request time.
        self.cup_definitions = {}   # cup_id -> dict from events_rank.json
        self.level_ids = {}         # level_filename -> level_id
        self._load_level_ids()
        self._load_events_rank()
        self._load_authentic_ghosts()
        self._load_authentic_cups()
        self._load_local_cup_replays()
        self._load_saved_player_replays()
        self._load_saved_challenge_replays()
        self._emulator_assets_synced = self._verify_cups_on_emulator() if sync_emulator else False
        if sync_emulator:
            self._load_outbox_replay()

    def _verify_cups_on_emulator(self, device: str = "emulator-5554") -> bool:
        """Check an optional development emulator cache; production never uses ADB."""
        if not ADB_PATH or not os.path.isdir(APK_CUPS_DIR) or not os.path.exists(ADB_PATH):
            return False
        try:
            uid = subprocess.run(
                [ADB_PATH, "-s", device, "shell", "stat", "-c", "%u", "/data/data/com.fingersoft.hcr2"],
                check=True, capture_output=True, text=True, timeout=10
            ).stdout.strip()
            for index in range(15):
                for filename in (
                    f"cup_hill_climb_cup{index}.dat",
                    f"ghost_{index}_0.dat",
                    f"ghost_{index}_1.dat",
                ):
                    check = subprocess.run(
                        [ADB_PATH, "-s", device, "shell", "su", uid, "-c", "test", "-r",
                         f"{ANDROID_CUPS_DIR}/{filename}"],
                        capture_output=True, timeout=10
                    )
                    if check.returncode != 0:
                        return False
                    if filename.startswith("ghost_"):
                        remote_path = f"{ANDROID_CUPS_DIR}/{filename}"
                        staged_path = f"/data/local/tmp/verify_{filename}"
                        stage_command = (
                            f'su -c "cp {remote_path} {staged_path} && chmod 644 {staged_path}"'
                        )
                        stage = subprocess.run(
                            [ADB_PATH, "-s", device, "shell", stage_command],
                            capture_output=True, text=True, timeout=10
                        )
                        if stage.returncode != 0:
                            raise RuntimeError(
                                f"failed to stage {filename}: {stage.stderr.strip()}"
                            )
                        local_path = os.path.join(BASE_DIR, f"verify_{filename}")
                        try:
                            subprocess.run(
                                [ADB_PATH, "-s", device, "pull", staged_path, local_path],
                                check=True, capture_output=True, text=True, timeout=20
                            )
                            with open(local_path, "rb") as staged_file:
                                device_bytes = staged_file.read()
                            with open(os.path.join(APK_CUPS_DIR, filename), "rb") as apk_file:
                                if device_bytes != apk_file.read():
                                    return False
                        finally:
                            if os.path.exists(local_path):
                                os.remove(local_path)
                        subprocess.run(
                            [ADB_PATH, "-s", device, "shell", "su", "-c",
                             f"rm -f {staged_path}"],
                            capture_output=True, text=True, timeout=10
                        )
            LOGGER.info("Verified all cached Cup and ghost files on emulator")
            return True
        except Exception as e:
            LOGGER.warning("Cup cache is not ready at startup: %s", e)
            return False

    def _load_outbox_replay(self, device: str = "emulator-5554"):
        """Optionally load a development replay template from a connected emulator."""
        if not ADB_PATH or not os.path.exists(ADB_PATH):
            return
        source = f"/data/data/com.fingersoft.hcr2/files/outbox/{OUTBOX_TEMPLATE}"
        local_path = os.path.join(BASE_DIR, OUTBOX_TEMPLATE)
        try:
            subprocess.run(
                [ADB_PATH, "-s", device, "shell", "su", "-c", f"cp {source} /data/local/tmp/{OUTBOX_TEMPLATE}"],
                check=True, capture_output=True, text=True, timeout=15
            )
            subprocess.run(
                [ADB_PATH, "-s", device, "shell", "su", "-c", f"chmod 644 /data/local/tmp/{OUTBOX_TEMPLATE}"],
                check=True, capture_output=True, text=True, timeout=10
            )
            subprocess.run(
                [ADB_PATH, "-s", device, "pull", f"/data/local/tmp/{OUTBOX_TEMPLATE}", local_path],
                check=True, capture_output=True, text=True, timeout=20
            )
            with open(local_path, "rb") as replay_file:
                replay = ReplayCls()
                replay.ParseFromString(replay_file.read())
            self.outbox_replay = replay
            LOGGER.info(
                "Loaded playable outbox replay template (%s/%s)",
                replay.levelId,
                replay.vehicle,
            )
        except Exception as e:
            LOGGER.warning("Could not load app outbox replay template: %s", e)
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    def _load_saved_player_replays(self):
        if not os.path.exists(REPLAYS_DIR):
            return
        count = 0
        for p in glob.glob(os.path.join(REPLAYS_DIR, "*.dat")):
            try:
                with open(p, "rb") as f:
                    r = ReplayCls()
                    r.ParseFromString(f.read())
                    lid = r.levelId or "unknown"
                    if lid not in self.player_replays:
                        self.player_replays[lid] = []
                    self.player_replays[lid].append(r)
                    replay_id = r._id if r.HasField("_id") else os.path.splitext(os.path.basename(p))[0]
                    if replay_id:
                        self._player_replay_index[replay_id] = r
                    count += 1
            except Exception:
                pass
        if count > 0:
            LOGGER.info("Loaded %s player replays across %s levels", count, len(self.player_replays))

    def _load_saved_challenge_replays(self):
        """Make persisted challenge recordings available to cup matchmaking."""
        count = 0
        for owner_id, profile in PlayerDB.iter_players():
            if not isinstance(profile, dict):
                continue
            challenge_records = profile.get("created_challenges", {})
            if not isinstance(challenge_records, dict):
                continue

            for record_key, record in challenge_records.items():
                try:
                    replay = ReplayCls()
                    replay.ParseFromString(bytes.fromhex(record.get("replay", "")))
                    replay_id = (
                        (replay._id if replay.HasField("_id") else "")
                        or record.get("challenge_id")
                        or record_key
                    )
                    if not replay_id or not replay.levelId or not replay.vehicle:
                        continue
                    if not self._has_playable_frame_data(replay):
                        continue
                    if replay_id in self._challenge_replay_index:
                        continue

                    replay._id = replay_id
                    replay.playerId = replay.playerId or record.get("player_id") or owner_id
                    if not replay.HasField("available"):
                        replay.available = True
                    if not replay.available:
                        continue
                    self.register_challenge_replay(replay)
                    count += 1
                except (AttributeError, TypeError, ValueError, DecodeError):
                    LOGGER.warning(
                        "Invalid persisted challenge replay %s for player %s",
                        record_key,
                        owner_id,
                    )

        if count:
            LOGGER.info("Loaded %s persisted challenge replays into cup ghost pool", count)

    def register_challenge_replay(self, replay):
        """Register one challenge recording for challenge-only cup matchmaking."""
        if not replay.HasField("_id") or not replay._id:
            raise ValueError("Challenge replay must have an ID")

        replay_id = replay._id
        clone = self._clone_replay(replay)
        previous = self._challenge_replay_index.get(replay_id)
        if previous is not None:
            self.challenge_replays[previous.levelId] = [
                item for item in self.challenge_replays.get(previous.levelId, [])
                if not item.HasField("_id") or item._id != replay_id
            ]
            self.player_replays[previous.levelId] = [
                item for item in self.player_replays.get(previous.levelId, [])
                if not item.HasField("_id") or item._id != replay_id
            ]

        self._challenge_replay_index[replay_id] = clone
        self.challenge_replays.setdefault(clone.levelId, []).append(clone)
        self._player_replay_index[replay_id] = clone
        level_replays = self.player_replays.setdefault(clone.levelId, [])
        if not any(item.HasField("_id") and item._id == replay_id for item in level_replays):
            level_replays.append(clone)
        return clone

    def _load_level_ids(self):
        levels_dir = os.path.join(DECRYPTED_DIR, "levels")
        if os.path.exists(levels_dir):
            for path in glob.glob(os.path.join(levels_dir, "*.json")):
                fname = os.path.basename(path)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        lid = data.get("id")
                        if lid:
                            self.level_ids[fname] = lid
                except Exception:
                    pass

    def _load_events_rank(self):
        path = os.path.join(DECRYPTED_DIR, "events_rank.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for ev in data.get("raceEvents", []):
                        cid = ev.get("id")
                        if cid:
                            self.cup_definitions[cid] = ev
            except Exception as e:
                LOGGER.exception("Error loading events_rank.json")

    def _load_authentic_ghosts(self):
        pattern = os.path.join(APK_CUPS_DIR, "ghost_*.dat")
        files = glob.glob(pattern)
        for p in files:
            fname = os.path.basename(p)
            try:
                with open(p, "rb") as f:
                    r = ReplayCls()
                    r.ParseFromString(f.read())
                    self.authentic_ghosts[fname] = r
            except Exception as e:
                LOGGER.warning("Failed to parse ghost %s: %s", fname, e)
        LOGGER.info("Loaded %s authentic ghosts", len(self.authentic_ghosts))

    def _load_authentic_cups(self):
        for path in glob.glob(os.path.join(APK_CUPS_DIR, "cup_*.dat")):
            filename = os.path.basename(path)
            try:
                with open(path, "rb") as f:
                    cup = CupCls()
                    cup.ParseFromString(f.read())
                self.authentic_cups[filename] = cup
            except Exception as e:
                LOGGER.warning("Failed to parse cup %s: %s", filename, e)
        LOGGER.info("Loaded %s authentic cup definitions", len(self.authentic_cups))

    def _load_local_cup_replays(self):
        if not os.path.isdir(CUP_REPLAYS_DIR):
            LOGGER.info("Local cup replay directory is unavailable: %s", CUP_REPLAYS_DIR)
            return

        count = 0
        pattern = os.path.join(CUP_REPLAYS_DIR, "**", "*.dat")
        for path in sorted(glob.glob(pattern, recursive=True)):
            try:
                with open(path, "rb") as replay_file:
                    replay = ReplayCls()
                    replay.ParseFromString(replay_file.read())

                if not replay.levelId or not replay.vehicle or not replay.playerId:
                    LOGGER.warning("Skipping cup replay with incomplete metadata: %s", path)
                    continue
                if replay.HasField("available") and not replay.available:
                    continue
                if self._extract_frame_data(replay) is None:
                    LOGGER.warning("Skipping cup replay with invalid frame data: %s", path)
                    continue

                relative_path = os.path.relpath(path, CUP_REPLAYS_DIR).replace(os.sep, "/")
                # Keep server-backed IDs distinct from the client's local "cups/" cache IDs.
                replay._id = f"more/{relative_path}"
                replay.available = True
                self.cup_replays.setdefault(replay.levelId, []).append(replay)
                self._cup_replay_index[replay._id] = replay
                count += 1
            except Exception as e:
                LOGGER.warning("Failed to load cup replay %s: %s", path, e)

        LOGGER.info("Loaded %s local cup replays across %s tracks", count, len(self.cup_replays))

    def get_track_ids_for_cup(self, cup_id: str) -> List[str]:
        ev = self.cup_definitions.get(cup_id)
        if not ev:
            return ["rookie_cup_01_01", "rookie_cup_02_01"]
        tracks = []
        for lf in ev.get("levels", []):
            lid = self.level_ids.get(lf, lf.replace(".json", ""))
            tracks.append(lid)
        return tracks or ["rookie_cup_01_01", "rookie_cup_02_01"]

    def create_cup_matchmaking(
        self,
        cup_id: str,
        vehicle_id: str,
        p_value: float,
        player_rank: float,
        content_version: int = 7,
        requester_player_id: Optional[str] = None,
    ) -> Tuple[List, any]:
        """
        Builds up to 3 distinct opponent Cups and their inline replay data.
        """
        tracks = self.get_track_ids_for_cup(cup_id)
        wc_race = WCRaceCls()
        cups = self._build_cups_from_track_replays(
            cup_id,
            tracks,
            vehicle_id,
            content_version,
            3,
            requester_player_id=requester_player_id,
        )
        for cup in cups:
            if not cup.replayIds:
                LOGGER.error("Cannot embed first-leg replay for empty cup %s", cup_id)
                cups = []
                wc_race.ClearField("Replays")
                break

            # The client consumes inline WCRace replays for the first leg only;
            # it requests each later leg using that index in Cup.replayIds.
            replay_id = cup.replayIds[0]
            replay = self._cup_matchmaking_replay(replay_id)
            if replay is None:
                LOGGER.error(
                    "Cannot embed cup replay %s for cup %s",
                    replay_id,
                    cup_id,
                )
                cups = []
                wc_race.ClearField("Replays")
                break
            client_replay = self.prepare_cup_replay(
                replay, content_version=content_version
            )
            if client_replay is None:
                LOGGER.error(
                    "Cup replay %s for cup %s has no valid FrameData payload",
                    replay_id,
                    cup_id,
                )
                cups = []
                wc_race.ClearField("Replays")
                break
            wc_race.Replays.add().CopyFrom(client_replay)
        opponent_owners = [
            [self._cup_matchmaking_replay(replay_id).playerId for replay_id in cup.replayIds]
            for cup in cups
        ]
        LOGGER.info(
            "Matchmaking cup '%s' using %s replay-backed opponent sets across tracks=%s with %s first-leg inline replays; owners=%s",
            cup_id,
            len(cups),
            tracks,
            len(wc_race.Replays),
            opponent_owners,
        )
        return cups, wc_race

    def _build_cups_from_track_replays(
        self,
        cup_id,
        tracks,
        vehicle_id,
        content_version,
        opponent_count,
        requester_player_id=None,
    ):
        """Build Cup records using playable replay IDs for each cup track."""
        if not tracks or opponent_count <= 0:
            return []
        replay_choices = [
            self._cup_track_replay_candidates(level_id, vehicle_id)
            for level_id in tracks
        ]
        if any(not candidates for candidates in replay_choices):
            replay_choices = [
                self._cup_track_replay_candidates(level_id, None)
                for level_id in tracks
            ]
        if any(not candidates for candidates in replay_choices):
            LOGGER.warning(
                "Cannot build cup %s: missing replay tracks %s",
                cup_id,
                [level_id for level_id, candidates in zip(tracks, replay_choices) if not candidates],
            )
            return []

        player_replays_by_track = []
        for candidates in replay_choices:
            by_player = {}
            for replay in candidates:
                if replay.playerId and replay.playerId != requester_player_id:
                    by_player.setdefault(replay.playerId, replay)
            player_replays_by_track.append(by_player)

        common_players = set(player_replays_by_track[0])
        for by_player in player_replays_by_track[1:]:
            common_players.intersection_update(by_player)
        if not common_players:
            LOGGER.warning(
                "Cannot build cup %s: no challenge player has a replay for every track %s",
                cup_id,
                tracks,
            )
            return []

        # Candidate lists are ranked, so keep the first track's ranking while
        # deduplicating owners. Each opponent then uses that owner's replay on
        # every track instead of combining unrelated players into one Cup.
        ordered_players = []
        seen_players = set()
        for replay in replay_choices[0]:
            player_id = replay.playerId
            if player_id in common_players and player_id not in seen_players:
                ordered_players.append(player_id)
                seen_players.add(player_id)

        if len(ordered_players) < opponent_count:
            LOGGER.warning(
                "Cup %s has only %s unique eligible opponents; requested %s",
                cup_id,
                len(ordered_players),
                opponent_count,
            )

        cups = []
        for player_id in ordered_players[:opponent_count]:
            selected = [by_player[player_id] for by_player in player_replays_by_track]
            cup = CupCls()
            cup.cupId = cup_id
            cup.ContentVersion = content_version
            cup.replayIds.extend(self._cup_replay_id(replay) for replay in selected)
            cups.append(cup)
        return cups

    @staticmethod
    def _has_playable_frame_data(replay):
        return bool(
            replay.zippedFrameData
            or replay.byteFrameData
            or bool(replay.frameData.frames)
            or bool(replay.frames)
        )

    @staticmethod
    def _extract_frame_data(replay):
        if replay.frameData.frames:
            frame_data = FrameDataCls()
            frame_data.CopyFrom(replay.frameData)
            return frame_data

        if replay.frames:
            frame_data = FrameDataCls()
            frame_data.frames.extend(replay.frames)
            return frame_data

        payloads = []
        if replay.byteFrameData:
            payloads.append(replay.byteFrameData)
        if replay.zippedFrameData:
            try:
                payloads.append(zlib.decompress(replay.zippedFrameData))
            except zlib.error:
                pass

        for payload in payloads:
            frame_data = FrameDataCls()
            try:
                frame_data.ParseFromString(payload)
            except DecodeError:
                continue
            if frame_data.frames:
                return frame_data
        return None

    def prepare_cup_replay(self, replay, content_version=None):
        """Return a replay in the raw byteFrameData form consumed by the client."""
        frame_data = self._extract_frame_data(replay)
        if frame_data is None or not frame_data.frames:
            return None

        clone = self._clone_replay(replay)
        clone.ClearField("frameData")
        clone.ClearField("frames")
        clone.ClearField("zippedFrameData")
        if content_version is not None and not clone.HasField("ContentVersion"):
            clone.ContentVersion = content_version
        clone.byteFrameData = frame_data.SerializeToString()
        return clone

    def _cup_track_replay_candidates(self, level_id, vehicle_id):
        local_candidates = [
            replay for replay in getattr(self, "cup_replays", {}).get(level_id, [])
            if replay.available
            and (vehicle_id is None or replay.vehicle == vehicle_id)
            and replay.HasField("_id")
            and replay._id
            and self._has_playable_frame_data(replay)
            and self._extract_frame_data(replay) is not None
        ]
        local_candidates = sorted(
            {replay._id: replay for replay in local_candidates}.values(),
            key=lambda replay: (-replay.distance, replay.time, replay._id),
        )
        local_ids = {replay._id for replay in local_candidates}
        challenge_candidates = [
            replay for replay in self._challenge_track_replay_candidates(level_id, vehicle_id)
            if replay._id not in local_ids
        ]
        return local_candidates + challenge_candidates

    def _cup_matchmaking_replay(self, replay_id):
        return (
            getattr(self, "_cup_replay_index", {}).get(replay_id)
            or getattr(self, "_challenge_replay_index", {}).get(replay_id)
        )

    def _challenge_track_replay_candidates(self, level_id, vehicle_id):
        candidates = [
            replay for replay in self.challenge_replays.get(level_id, [])
            if replay.available
            and (vehicle_id is None or replay.vehicle == vehicle_id)
            and replay.HasField("_id")
            and replay._id
            and self._has_playable_frame_data(replay)
            and self._extract_frame_data(replay) is not None
        ]
        unique = {replay._id: replay for replay in candidates}
        return sorted(
            unique.values(),
            key=lambda replay: (-replay.distance, replay.time, replay._id),
        )

    def _track_replay_candidates(self, level_id, vehicle_id):
        def matches_vehicle(replay):
            return vehicle_id is None or replay.vehicle == vehicle_id

        candidates = [
            replay for replay in self.player_replays.get(level_id, [])
            if replay.available
            and matches_vehicle(replay)
            and replay.HasField("_id")
            and self._has_playable_frame_data(replay)
        ]
        candidates.extend(
            replay for replay in self.authentic_ghosts.values()
            if replay.levelId == level_id
            and matches_vehicle(replay)
            and self._has_playable_frame_data(replay)
        )
        unique = {}
        for replay in candidates:
            unique[self._cup_replay_id(replay)] = replay
        return sorted(unique.values(), key=lambda replay: (-replay.distance, replay.time, self._cup_replay_id(replay)))

    def _cup_replay_id(self, replay):
        if replay.HasField("_id") and replay._id:
            return replay._id
        for filename, candidate in self.authentic_ghosts.items():
            if candidate is replay:
                return f"cups/{filename}"
        return ""

    def _pick_track_replay(self, level_id, vehicle_id, opponent_index):
        candidates = [
            replay for replay in self.player_replays.get(level_id, [])
            if replay.available and replay.vehicle == vehicle_id and replay.HasField("_id")
        ]
        candidates.extend(
            replay for replay in self.authentic_ghosts.values()
            if replay.levelId == level_id and replay.vehicle == vehicle_id and replay.HasField("_id")
        )
        if not candidates:
            return None
        candidates.sort(key=lambda replay: (-replay.distance, replay.time, replay._id))
        return candidates[opponent_index % len(candidates)]


    def sync_cups_to_emulator(self, device: str = "emulator-5554") -> bool:
        """Copy authentic cup/replay files into the app-private cache on device."""
        if not ADB_PATH or not os.path.exists(ADB_PATH) or not os.path.isdir(APK_CUPS_DIR):
            LOGGER.info("ADB or extracted APK cup assets unavailable; skipping device sync")
            return False

        try:
            devices = subprocess.run(
                [ADB_PATH, "devices"], check=True, capture_output=True, text=True, timeout=10
            ).stdout.splitlines()
            if not any(line.split()[:2] == [device, "device"] for line in devices[1:]):
                LOGGER.warning("ADB device %s is not online; skipping cup asset sync", device)
                return False

            app_uid = subprocess.run(
                [ADB_PATH, "-s", device, "shell", "stat", "-c", "%u", "/data/data/com.fingersoft.hcr2"],
                check=True, capture_output=True, text=True, timeout=10
            ).stdout.strip()
            destination = ANDROID_CUPS_DIR
            setup = subprocess.run(
                [ADB_PATH, "-s", device, "shell", "su", "-c",
                 f"mkdir -p {destination} && chown {app_uid}:{app_uid} {destination}"],
                capture_output=True, text=True, timeout=10
            )
            if setup.returncode != 0:
                # Root may report a nonzero status when ownership is already
                # correct; verify the usable state rather than trusting it.
                LOGGER.warning(
                    "Cache setup returned %s; checking readability",
                    setup.returncode,
                )

            readable = subprocess.run(
                [ADB_PATH, "-s", device, "shell", "su", app_uid, "-c",
                 "test", "-r", destination],
                capture_output=True, text=True, timeout=10
            )
            if readable.returncode != 0:
                raise RuntimeError("app UID cannot read the private cups cache directory")

            filenames = sorted(
                name for name in os.listdir(APK_CUPS_DIR)
                if name.startswith("cup_hill_climb_cup") or name.startswith("ghost_")
            )
            outbox_source = f"/data/data/com.fingersoft.hcr2/files/outbox/{OUTBOX_TEMPLATE}"
            outbox_read = subprocess.run(
                [ADB_PATH, "-s", device, "shell", "su", app_uid, "-c", "test", "-r", outbox_source],
                capture_output=True, text=True, timeout=10
            )
            if outbox_read.returncode != 0:
                raise RuntimeError(f"app UID cannot read outbox template {OUTBOX_TEMPLATE}")
            for filename in filenames:
                with open(os.path.join(APK_CUPS_DIR, filename), "rb") as asset_file:
                    content = asset_file.read()

                temp_path = f"/data/local/tmp/{filename}"
                with open(os.path.join(BASE_DIR, filename), "wb") as staged_file:
                    staged_file.write(content)
                try:
                    subprocess.run(
                        [ADB_PATH, "-s", device, "push", os.path.join(BASE_DIR, filename), temp_path],
                        check=True, capture_output=True, text=True, timeout=20
                    )
                finally:
                    os.remove(os.path.join(BASE_DIR, filename))
                copied = subprocess.run(
                    [ADB_PATH, "-s", device, "shell", "su", "-c",
                     f"cp {temp_path} {destination}/{filename}"],
                    capture_output=True, text=True, timeout=10
                )
                if copied.returncode != 0:
                    raise RuntimeError(f"failed to copy {filename}: {copied.stderr.strip()}")
                owned = subprocess.run(
                    [ADB_PATH, "-s", device, "shell", "su", "-c",
                     f"chown {app_uid}:{app_uid} {destination}/{filename}"],
                    capture_output=True, text=True, timeout=10
                )
                if owned.returncode != 0:
                    raise RuntimeError(f"failed to set owner on {filename}: {owned.stderr.strip()}")

            for idx in range(15):
                for filename in (
                    f"cup_hill_climb_cup{idx}.dat",
                    f"ghost_{idx}_0.dat",
                    f"ghost_{idx}_1.dat",
                ):
                    check = subprocess.run(
                        [ADB_PATH, "-s", device, "shell", "su", app_uid, "-c",
                         "test", "-r", f"{destination}/{filename}"],
                        capture_output=True, text=True, timeout=10
                    )
                    if check.returncode != 0:
                        raise RuntimeError(f"app UID cannot read {filename}")
                    if filename.startswith("ghost_"):
                        remote_path = f"{destination}/{filename}"
                        temp_path = f"/data/local/tmp/verify_{filename}"
                        subprocess.run(
                            [ADB_PATH, "-s", device, "shell", "su", "-c",
                             f"cp {remote_path} {temp_path}"],
                            check=True, capture_output=True, text=True, timeout=10
                        )
                        subprocess.run(
                            [ADB_PATH, "-s", device, "shell", "su", "-c",
                             f"chmod 644 {temp_path}"],
                            check=True, capture_output=True, text=True, timeout=10
                        )
                        local_path = os.path.join(BASE_DIR, f"verify_{filename}")
                        try:
                            subprocess.run(
                                [ADB_PATH, "-s", device, "pull", temp_path, local_path],
                                check=True, capture_output=True, text=True, timeout=20
                            )
                            with open(local_path, "rb") as replay_file:
                                contents = replay_file.read()
                        finally:
                            if os.path.exists(local_path):
                                os.remove(local_path)
                        if contents != open(os.path.join(APK_CUPS_DIR, filename), "rb").read():
                            raise RuntimeError(f"staged replay {filename} differs from APK asset")
            LOGGER.info(
                "Synced and verified %s playable cup assets on %s",
                len(filenames),
                device,
            )
            return True
        except Exception as e:
            LOGGER.exception("Emulator cup asset sync failed")
            return False

    def get_replays_for_track(
        self,
        level_id: str,
        vehicle_id: str,
        p_value: float,
        player_rank: float,
        replay_ids: Optional[List[str]] = None,
        count: int = 3
    ) -> List:
        """
        Retrieves or synthesizes replays for a specific level.
        Prioritizes authentic uploaded player replays if available.
        """
        replays = []

        # Prefer authentic runs uploaded for this exact level and vehicle.
        available_player_replays = [
            replay for replay in self.player_replays.get(level_id, [])
            if replay.available
            and replay.vehicle == vehicle_id
            and self._has_playable_frame_data(replay)
        ]
        selected = random.sample(available_player_replays, min(count, len(available_player_replays)))
        replays.extend(self._clone_replay(replay) for replay in selected)

        # Cup opponents can also be built from ordinary level replays. The
        # generated Cup below references these IDs, which resolve through
        # get_cup_replays when the client requests the actual ghost data.
        if len(replays) < count:
            candidates = [
                replay
                for replay in self.authentic_ghosts.values()
                if replay.levelId == level_id and replay.vehicle == vehicle_id
            ]
            candidates.extend(
                replay
                for replay in self._player_replay_index.values()
                if replay.levelId == level_id
                and replay.vehicle == vehicle_id
                and replay.available
                and self._has_playable_frame_data(replay)
            )
            existing_ids = {replay._id for replay in replays if replay.HasField("_id")}
            candidates = [
                replay for replay in candidates
                if not replay.HasField("_id") or replay._id not in existing_ids
            ]
            random.shuffle(candidates)
            replays.extend(self._clone_replay(replay) for replay in candidates[:count - len(replays)])

        # If the requested track has fewer than count distinct real replays,
        # return what exists; do not fabricate or substitute another track.
        return replays

    @staticmethod
    def _clone_replay(replay):
        clone = ReplayCls()
        clone.CopyFrom(replay)
        return clone

    def get_cup_replays(self, replay_ids: List[str]) -> List:
        """Resolve Cup replay IDs against packaged assets and uploaded replays."""
        replays = []
        for replay_id in replay_ids:
            filename = os.path.basename(replay_id)
            source = (
                self._cup_matchmaking_replay(replay_id)
                or self.authentic_ghosts.get(filename)
                or self._player_replay_index.get(filename)
            )
            if source is None and filename.endswith(".dat"):
                source = self._player_replay_index.get(os.path.splitext(filename)[0])
            if source is None:
                continue
            replays.append(self._clone_replay(source))
        return replays

    def store_player_replay(self, player_id: str, replay_msg) -> str:
        """
        Persists an uploaded player replay to disk and registers in active ghost pool.
        """
        ts = int(time.time())
        rand_suffix = random.randint(1000, 9999)
        replay_key = f"replay_{player_id[:8]}_{ts}_{rand_suffix}"
        file_path = os.path.join(REPLAYS_DIR, f"{replay_key}.dat")

        try:
            os.makedirs(REPLAYS_DIR, exist_ok=True)
            # Preserve all client-provided replay and frame fields exactly; only
            # fill identity/metadata defaults that the wire payload omitted.
            if not replay_msg.playerId:
                replay_msg.playerId = player_id
            if not replay_msg.HasField("available"):
                replay_msg.available = True
            if not replay_msg.vehicle:
                replay_msg.vehicle = "jeep"
            if not replay_msg.levelId:
                replay_msg.levelId = "rookie_cup_01_01"
            if not replay_msg.HasField("time"):
                replay_msg.time = 30.0

            frame_bytes = (
                len(replay_msg.byteFrameData)
                + len(replay_msg.zippedFrameData)
                + len(replay_msg.frames)
                + len(replay_msg.frameData.frames)
            )
            if frame_bytes == 0:
                LOGGER.warning(
                    "Replay %s from %s has no frame payload; storing metadata only, not eligible as a ghost",
                    replay_key,
                    player_id,
                )

            replay_msg._id = replay_key
            with open(file_path, "wb") as f:
                f.write(replay_msg.SerializeToString())
            LOGGER.info(
                "Stored player replay '%s' (size: %s bytes)",
                replay_key,
                os.path.getsize(file_path),
            )

            # Index by replay ID for Cup references and keep level-indexed rows
            # for leaderboards and track replay requests.
            clone = self._clone_replay(replay_msg)
            self._player_replay_index[replay_key] = clone
            lid = replay_msg.levelId
            self.player_replays.setdefault(lid, []).append(clone)

        except Exception as e:
            LOGGER.exception("Failed to save replay %s", replay_key)

        return replay_key

# Global singleton
ghost_mgr = GhostManager()
