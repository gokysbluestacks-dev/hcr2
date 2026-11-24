"""
Hill Climb Racing 2 - Enhanced Message Handlers
Integrates decrypted game configs (gamedata.json, economy.json, events_rank.json, tournaments.json)
and full server-side Cup matchmaking & Ghost replay serving.
"""

import json
import logging
import os
import time

from google.protobuf.message import DecodeError

from db import PlayerDB
from ghost_manager import ghost_mgr, REPLAYS_DIR
from hcr2_proto import get_message_class

FSMessageCls = get_message_class("FSMessage")
GameStatusCls = get_message_class("GameStatus")
GameParametersCls = get_message_class("GameParameters")
CupCls = get_message_class("Cup")
WCRaceCls = get_message_class("WCRace")
ReplayCls = get_message_class("Replay")
FrameDataCls = get_message_class("FrameData")


def _frame_summary_for_log(byte_frame_data):
    frame_data = FrameDataCls()
    frame_data.ParseFromString(byte_frame_data)
    frames_with_transform = sum(
        frame.HasField("transform") for frame in frame_data.frames
    )
    body_transform_count = sum(
        len(frame.transform.bodyTransforms)
        for frame in frame_data.frames
        if frame.HasField("transform")
    )
    return len(frame_data.frames), frames_with_transform, body_transform_count


# MessageType constants
MSG_HANDSHAKE                     = 1
MSG_STORE_REPLAY                  = 2
MSG_REQUEST_REPLAYS               = 6
MSG_GET_PARAMETERS                = 11
MSG_STORE_CHALLENGE_REPLAY        = 19
MSG_REQUEST_WC_RACE_REPLAYS       = 21
MSG_REQUEST_DIVISION_RACE_REPLAYS = 22
MSG_STORE_TEAM_REPLAY             = 26
MSG_CREATE_CHALLENGE               = 27
MSG_UPDATE_CHALLENGE               = 28
CHALLENGE_CREATE_RESPONSE_SUCCESS  = 1
MSG_REQUEST_CHALLENGES             = 29
MSG_CREATE_CUP                   = 30
MSG_REQUEST_CUPS                  = 31
MSG_STORE_GAME_STATUS             = 39
MSG_REQUEST_GAME_STATUS           = 40
MSG_REQUEST_FRIENDLY_RACES        = 41
MSG_ACCEPT_INVITE                 = 48
MSG_REQUEST_FRIENDS               = 49
MSG_ADD_FRIENDS                   = 50
MSG_SET_TEST_GROUP                = 51
MSG_REMOVE_FRIEND                 = 52
MSG_REQUEST_PLAYER_INFOS           = 53
MSG_REQUEST_BOSS_CUP              = 54
# Leaderboard request message IDs observed from the game client.
MSG_REQUEST_LEADERBOARD_STANDINGS = 23
MSG_REQUEST_LEADERBOARD           = 4

LOGGER = logging.getLogger("hcr2.handlers")
DECRYPTED_DIR = os.path.expanduser(os.environ.get(
    "HCR2_DECRYPTED_DIR", os.path.join(os.path.expanduser("~"), "decrypted_output")
))

def load_decrypted_json(filename: str):
    path = os.path.join(DECRYPTED_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            LOGGER.exception("Failed to read config file %s", filename)
    return None

class MessageDispatcher:
    def __init__(self, session_id: int):
        self.session_id = session_id
        self.player_id = "default_player"

    def handle(self, in_msg) -> list:
        msg_type = in_msg.MessageType
        responses = []

        LOGGER.info(
            "Dispatching MessageType=%s, Session=%s, PlayerId=%r",
            msg_type,
            in_msg.Session,
            in_msg.PlayerId,
        )


        if in_msg.PlayerId:
            self.player_id = in_msg.PlayerId

        if msg_type == 47:
            LOGGER.info(
                "MessageType 47 payload fields=%s",
                [field.name for field, _ in in_msg.ListFields()],
            )

        if msg_type in (MSG_HANDSHAKE, 0) or in_msg.HasField("BuildSignature"):
            responses.append(self._handle_handshake(in_msg))
        elif msg_type == MSG_GET_PARAMETERS:
            responses.append(self._handle_get_parameters(in_msg))
        elif msg_type == MSG_REQUEST_GAME_STATUS:
            responses.append(self._handle_request_game_status(in_msg))
        elif msg_type == MSG_STORE_GAME_STATUS:
            responses.append(self._handle_store_game_status(in_msg))
        elif msg_type == MSG_REQUEST_CUPS:
            responses.append(self._handle_request_cups(in_msg))
        elif msg_type in (MSG_REQUEST_WC_RACE_REPLAYS, MSG_REQUEST_DIVISION_RACE_REPLAYS):
            responses.append(self._handle_request_wc_race_replays(in_msg))
        elif msg_type in (MSG_STORE_REPLAY, MSG_STORE_CHALLENGE_REPLAY, MSG_STORE_TEAM_REPLAY):
            responses.append(self._handle_store_replay(in_msg))
        elif msg_type == MSG_CREATE_CUP:
            responses.append(self._handle_create_cup(in_msg))
        elif msg_type == MSG_REQUEST_REPLAYS:
            responses.append(self._handle_request_replays(in_msg))
        elif msg_type == MSG_REQUEST_FRIENDLY_RACES:
            responses.append(self._handle_request_friendly_races(in_msg))
        elif msg_type == MSG_UPDATE_CHALLENGE:
            responses.append(self._handle_update_challenge(in_msg))
        elif msg_type == MSG_CREATE_CHALLENGE:
            responses.append(self._handle_create_challenge(in_msg))
        elif msg_type == MSG_REQUEST_CHALLENGES:
            responses.append(self._handle_request_challenges(in_msg))
        elif msg_type == MSG_REQUEST_FRIENDS:
            responses.append(self._handle_request_friends(in_msg))
        elif msg_type == MSG_REQUEST_PLAYER_INFOS:
            responses.append(self._handle_request_player_infos(in_msg))
        elif msg_type == MSG_ADD_FRIENDS:
            responses.append(self._handle_add_friends(in_msg))
        elif msg_type == MSG_REMOVE_FRIEND:
            responses.append(self._handle_remove_friend(in_msg))
        elif msg_type == MSG_ACCEPT_INVITE:
            responses.append(self._handle_accept_invite(in_msg))
        elif msg_type == MSG_REQUEST_LEADERBOARD:
            responses.append(self._handle_request_leaderboard(in_msg))
        elif msg_type == MSG_REQUEST_LEADERBOARD_STANDINGS:
            responses.append(self._handle_request_leaderboard_standings(in_msg))
        elif msg_type == MSG_REQUEST_BOSS_CUP:
            responses.append(self._handle_request_boss_cup(in_msg))
        else:
            LOGGER.warning("Unhandled MessageType %s; sending standard ACK", msg_type)
            responses.append(self._build_generic_ack(in_msg))

        return responses

    def _handle_handshake(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_HANDSHAKE
        out.ResponseCode = 0  # OK
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber
        out.HandshakeResponse = 3  # Accepted / Success (required by client dispatchHandshake)
        out.HandshakeMessage = "Handshake success"
        if in_msg.ContentVersion:
            out.ContentVersion = in_msg.ContentVersion
        else:
            out.ContentVersion = 7  # from gamedata.json
        if in_msg.Version:
            for v in in_msg.Version:
                out.Version.append(v)
        else:
            out.Version.append(153)
        LOGGER.info("Handshake accepted, MessageNumber=%s", in_msg.MessageNumber)
        return out

    def _handle_get_parameters(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_GET_PARAMETERS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        params = out.GameParameters
        params.serverTime = int(time.time())

        # Load real decrypted JSON files to push to the client
        config_files = [
            ("gamedata.json", "gamedata"),
            ("economy.json", "economy"),
            ("events_rank.json", "events_rank"),
            ("tournaments.json", "tournaments"),
            ("customizations.json", "customizations"),
            ("achievements.json", "achievements"),
            ("worlds.json", "worlds"),
        ]

        count = 0
        for fname, conf_name in config_files:
            content = load_decrypted_json(fname)
            if content:
                obj = params.jsonObjects.add()
                obj.name = conf_name
                obj.data = content
                count += 1

        if count == 0:
            obj = params.jsonObjects.add()
            obj.name = "GameTuning"
            obj.data = '{"doubleCoins": true, "vipActive": true}'

        LOGGER.info("Served GameParameters with %s config JSON objects", count)
        return out

    def _handle_request_game_status(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_GAME_STATUS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        profile = PlayerDB.load_player(self.player_id)
        status = out.GameStatus
        status.playerId = self.player_id
        status.playerName = self.player_id
        status.totalCoinsCollected = profile.get("coins", 0)
        status.diamonds = profile.get("diamonds", 0)
        status.playerXp = profile.get("xp", 0)
        status.WCRank = profile.get("rank", 0.0)
        status.cloudSaveVersion = profile.get("cloud_save_version", 0)
        status.adFree = profile.get("ad_free", False)

        for unlock in profile.get("unlocks", []):
            item = status.unlocks.add()
            item.type = unlock.get("type", 0)
            item.id = unlock.get("id", "")
            item.unlockState = unlock.get("unlockState", 0)
            item.unlockType = unlock.get("unlockType", 0)

        for v in profile.get("vehicles", []):
            status.unlockedVehicles.append(v)

        for w in profile.get("worlds", []):
            status.ownedWorlds.append(w)

        LOGGER.info("Sent GameStatus for player %s", self.player_id)
        return out

    def _handle_store_game_status(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_STORE_GAME_STATUS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        if in_msg.HasField("GameStatus"):
            saved = PlayerDB.update_from_game_status(self.player_id, in_msg.GameStatus)
            LOGGER.info("Stored GameStatus for player %s", self.player_id)

        return out

    def _handle_request_cups(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_CUPS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        if in_msg.CupId:
            # Client is entering matchmaking for a specific cup!
            profile = PlayerDB.load_player(self.player_id)
            player_rank = profile.get("rank", 0.0)
            vehicle_id = in_msg.VehicleId if in_msg.VehicleId else "jeep"
            p_value = in_msg.PValue if in_msg.PValue else 4.0
            content_version = in_msg.ContentVersion if in_msg.ContentVersion else 7
            LOGGER.info(
                "[Cups] Matchmaking request: cup=%s vehicle=%s content_version=%s p_value=%s",
                in_msg.CupId,
                vehicle_id,
                content_version,
                p_value,
            )

            cups, wc_race = ghost_mgr.create_cup_matchmaking(
                cup_id=in_msg.CupId,
                vehicle_id=vehicle_id,
                p_value=p_value,
                player_rank=player_rank,
                content_version=content_version,
                requester_player_id=self.player_id,
            )

            expected_replay_count = len(cups)
            if cups and len(wc_race.Replays) != expected_replay_count:
                LOGGER.error(
                    "[Cups] Refusing incomplete inline replay payload for %s: expected=%s actual=%s",
                    in_msg.CupId,
                    expected_replay_count,
                    len(wc_race.Replays),
                )
                cups = []
                wc_race.ClearField("Replays")

            for c in cups:
                cup = out.Cups.add()
                cup.CopyFrom(c)

            out.WCRace.CopyFrom(wc_race)
            out.SendCupReplays = bool(cups)
            if cups:
                cup_summary = [
                    (cup.cupId, cup.ContentVersion, list(cup.replayIds))
                    for cup in cups
                ]
                LOGGER.info(
                    "[Cups] Type 31 response: ResponseCode=%s, SendCupReplays=%s, InlineReplays=%s, Cups=%s",
                    out.ResponseCode,
                    out.SendCupReplays,
                    len(out.WCRace.Replays),
                    cup_summary,
                )
                LOGGER.info(
                    "[Cups] Inline replay payloads: %s",
                    [
                        (
                            replay._id,
                            replay.levelId,
                            replay.playerId,
                            replay.vehicle,
                            replay.ContentVersion if replay.HasField("ContentVersion") else None,
                            replay.levelType if replay.HasField("levelType") else None,
                            replay.finishingStatus if replay.HasField("finishingStatus") else None,
                            replay.time,
                            replay.distance,
                            _frame_summary_for_log(replay.byteFrameData),
                            len(replay.byteFrameData),
                            [field.name for field, _ in replay.ListFields()],
                        )
                        for replay in out.WCRace.Replays
                    ],
                )

            if not cups:
                # An empty matchmaking result is safer than returning replay IDs
                # that cannot be loaded; keep the response explicit in logs.
                LOGGER.warning("[Cups] No complete replay sets available for %s", in_msg.CupId)
            else:
                LOGGER.info("[Cups] Served matchmaking for %s with %s opponents", in_msg.CupId, len(cups))
        else:
            # Client is querying all available cups for UI list
            events_json = load_decrypted_json("events_rank.json")
            cup_ids = []
            if events_json:
                try:
                    data = json.loads(events_json)
                    cup_ids = [ev.get("id") for ev in data.get("raceEvents", []) if ev.get("id")]
                except Exception:
                    pass

            if not cup_ids:
                cup_ids = ["hill_climb_cup", "big_air_cup", "countryside_cup", "winter_cup_easy"]

            for cid in cup_ids:
                cup = out.Cups.add()
                cup.cupId = cid
                cup.ContentVersion = 7

            LOGGER.info("[Cups] Sent %s Cups for UI list", len(cup_ids))

        return out

    def _handle_request_wc_race_replays(self, in_msg):
        out = FSMessageCls()
        out.MessageType = in_msg.MessageType
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        profile = PlayerDB.load_player(self.player_id)
        player_rank = profile.get("rank", 0.0)

        level_id = in_msg.LevelId if in_msg.LevelId else "rookie_cup_01_01"
        vehicle_id = in_msg.VehicleId if in_msg.VehicleId else "jeep"
        p_value = in_msg.PValue if in_msg.PValue else 4.0
        content_version = (
            in_msg.ContentVersion if in_msg.HasField("ContentVersion") else 7
        )
        replay_ids = list(in_msg.ReplayIds) if in_msg.ReplayIds else None
        replays = []
        if replay_ids:
            LOGGER.info("[Replays] Client requested replay IDs: %s", replay_ids)
            unresolved = []
            invalid_payloads = []
            for replay_id in replay_ids:
                matches = ghost_mgr.get_cup_replays([replay_id])
                if not matches:
                    unresolved.append(replay_id)
                    continue
                replay = matches[0]
                client_replay = ghost_mgr.prepare_cup_replay(
                    replay, content_version=content_version
                )
                if client_replay is None:
                    invalid_payloads.append(replay_id)
                    continue
                replays.append(client_replay)
                LOGGER.info(
                    "[Replays] Resolved %s: level=%s vehicle=%s byte_frame_data=%s",
                    replay_id,
                    client_replay.levelId,
                    client_replay.vehicle,
                    len(client_replay.byteFrameData),
                )
            if unresolved:
                LOGGER.warning(
                    "[Replays] Could not resolve requested replay IDs: %s (resolved=%s/%s)",
                    unresolved,
                    len(replays),
                    len(replay_ids),
                )
            if invalid_payloads:
                LOGGER.warning(
                    "[Replays] Requested replay IDs have invalid frame payloads: %s",
                    invalid_payloads,
                )
        else:
            source_replays = ghost_mgr.get_replays_for_track(
                level_id=level_id,
                vehicle_id=vehicle_id,
                p_value=p_value,
                player_rank=player_rank,
                replay_ids=replay_ids,
                count=3
            )
            for replay in source_replays:
                client_replay = ghost_mgr.prepare_cup_replay(
                    replay, content_version=content_version
                )
                if client_replay is not None:
                    replays.append(client_replay)

        for replay in replays:
            out.WCRace.Replays.add().CopyFrom(replay)

        LOGGER.info("[Replays] Served %s replays for track %s", len(replays), level_id)
        return out

    def _handle_create_cup(self, in_msg):
        """Acknowledge a completed online cup submitted by the game client."""
        out = FSMessageCls()
        out.MessageType = MSG_CREATE_CUP
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        LOGGER.info(
            "[Cups] Accepted cup result: cups=%s finish_position=%s replays=%s",
            [(cup.cupId, list(cup.replayIds)) for cup in in_msg.Cups],
            in_msg.FinishPosition if in_msg.HasField("FinishPosition") else None,
            len(in_msg.Replays),
        )
        return out

    def _handle_store_replay(self, in_msg):
        out = FSMessageCls()
        out.MessageType = in_msg.MessageType
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        if in_msg.HasField("Replay"):
            replay = in_msg.Replay
            key = ghost_mgr.store_player_replay(self.player_id, replay)
            out.Key = key
            LOGGER.info(
                "[Replays] Stored replay for player=%s level=%s vehicle=%s time=%.3f distance=%.2f frame_bytes=%s zipped_bytes=%s frames=%s frame_data=%s key=%s",
                self.player_id,
                replay.levelId,
                replay.vehicle,
                replay.time,
                replay.distance,
                len(replay.byteFrameData),
                len(replay.zippedFrameData),
                len(replay.frames),
                len(replay.frameData.frames),
                key,
            )
        else:
            out.Key = f"replay_{self.player_id}_{int(time.time())}"

        return out

    def _handle_request_replays(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_REPLAYS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        for rid in in_msg.ReplayIds:
            replay_matches = ghost_mgr.get_cup_replays([rid])
            if replay_matches:
                replay = replay_matches[0]
            else:
                replay_path = os.path.join(REPLAYS_DIR, f"{os.path.basename(rid)}.dat")
                if not os.path.isfile(replay_path):
                    continue
                try:
                    replay = ReplayCls()
                    with open(replay_path, "rb") as replay_file:
                        replay.ParseFromString(replay_file.read())
                except (OSError, ValueError, DecodeError) as exc:
                    LOGGER.warning("Could not load requested replay %s: %s", rid, exc)
                    continue

            client_replay = ghost_mgr.prepare_cup_replay(replay)
            if client_replay is None:
                LOGGER.warning("Requested replay %s has no valid FrameData payload", rid)
                continue
            out.Replays.add().CopyFrom(client_replay)
        LOGGER.info("[Replays] Served %s replays by ID", len(out.Replays))
        return out

    def _handle_request_friendly_races(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_FRIENDLY_RACES
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber
        return out

    def _handle_create_challenge(self, in_msg):
        """Accept a client-created challenge with its replay and vehicle setup."""
        out = FSMessageCls()
        out.MessageType = MSG_CREATE_CHALLENGE
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        if not in_msg.HasField("Challenge"):
            LOGGER.warning("[Challenges] Create request omitted Challenge payload")
            return out

        challenge = in_msg.Challenge
        if not challenge.HasField("challengerReplay"):
            LOGGER.warning("[Challenges] Create request omitted challenger replay")
            return out
        if not challenge.HasField("vehicleStatus"):
            LOGGER.warning("[Challenges] Create request omitted vehicle status")
            return out

        replay = challenge.challengerReplay
        vehicle_status = challenge.vehicleStatus
        if not replay.HasField("zippedFrameData") or not replay.zippedFrameData:
            LOGGER.warning("[Challenges] Create request replay has no compressed frame data")
            return out
        if not replay.levelId or not replay.vehicle:
            LOGGER.warning("[Challenges] Create request replay is missing level or vehicle")
            return out
        if vehicle_status.vehicleId and vehicle_status.vehicleId != replay.vehicle:
            LOGGER.warning(
                "[Challenges] Vehicle mismatch: replay=%s status=%s",
                replay.vehicle,
                vehicle_status.vehicleId,
            )
            return out

        challenge_id = challenge.challengeId or f"challenge_{self.player_id[:8]}_{int(time.time())}"
        replay_copy = ReplayCls()
        replay_copy.CopyFrom(replay)
        replay_copy.playerId = self.player_id
        replay_copy.playerName = replay.playerName or PlayerDB.load_player(self.player_id).get(
            "player_name", self.player_id
        )
        replay_copy.available = True
        if not replay_copy.HasField("time"):
            replay_copy.time = 30.0
        if not replay_copy.HasField("distance"):
            replay_copy.distance = 0.0
        replay_copy._id = challenge_id

        profile = PlayerDB.load_player(self.player_id)
        challenges = profile.setdefault("created_challenges", {})
        challenges[challenge_id] = {
            "challenge_id": challenge_id,
            "player_id": self.player_id,
            "level_id": replay_copy.levelId,
            "vehicle_id": replay_copy.vehicle,
            "replay": replay_copy.SerializeToString().hex(),
            "created_at": int(time.time()),
            "total_tries": challenge.totalTries,
            "total_wins": challenge.totalWins,
            "total_losses": challenge.totalLosses,
        }
        PlayerDB.save_player(self.player_id, profile)

        ghost_mgr.register_challenge_replay(replay_copy)

        # The game maps this response code to RequestStatus and accepts 1 as success.
        out.ResponseCode = CHALLENGE_CREATE_RESPONSE_SUCCESS
        out.ChallengeId = challenge_id
        LOGGER.info(
            "[Challenges] Saved created challenge %s from %s: level=%s vehicle=%s replay_bytes=%s",
            challenge_id,
            self.player_id,
            replay_copy.levelId,
            replay_copy.vehicle,
            len(replay_copy.zippedFrameData),
        )
        return out

    def _handle_update_challenge(self, in_msg):
        """Persist a challenge update reported by the game client."""
        out = FSMessageCls()
        out.MessageType = MSG_UPDATE_CHALLENGE
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        if in_msg.HasField("Challenge"):
            challenge = in_msg.Challenge
            LOGGER.info(
                "[Challenges] Received update for challenge %r "
                "(tries=%s, wins=%s, losses=%s)",
                challenge.challengeId,
                challenge.totalTries,
                challenge.totalWins,
                challenge.totalLosses,
            )
        else:
            LOGGER.warning("[Challenges] MessageType 27 did not include Challenge payload")
        return out

    def _handle_request_challenges(self, in_msg):
        """Offer saved authentic replays as local, asynchronous challenges."""
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_CHALLENGES
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        challenge_ids = list(in_msg.ChallengeIds)
        if in_msg.HasField("ChallengeId") and in_msg.ChallengeId:
            challenge_ids.append(in_msg.ChallengeId)

        known_replays = [
            replay
            for level_replays in ghost_mgr.player_replays.values()
            for replay in level_replays
            if replay.playerId and replay.playerId != self.player_id
            and ghost_mgr._has_playable_frame_data(replay)
        ]
        profile = PlayerDB.load_player(self.player_id)
        for owner_id, owner_profile in PlayerDB.iter_players():
            if owner_id == self.player_id:
                continue
            for challenge_data in owner_profile.get("created_challenges", {}).values():
                try:
                    replay = ReplayCls()
                    replay.ParseFromString(bytes.fromhex(challenge_data.get("replay", "")))
                    if replay.playerId and replay.HasField("zippedFrameData"):
                        known_replays.append(replay)
                except (ValueError, TypeError):
                    LOGGER.warning("Invalid persisted challenge replay for player %s", owner_id)
        known_ids = set()
        for replay in known_replays:
            replay_id = replay._id if replay.HasField("_id") else ""
            stable_id = replay_id or f"{replay.playerId}:{replay.levelId}"
            if stable_id in known_ids:
                continue
            known_ids.add(stable_id)
            if challenge_ids and stable_id not in challenge_ids and replay_id not in challenge_ids:
                continue

            challenge = out.Challenges.add()
            challenge.challengeId = replay_id or stable_id
            challenge.expirationTimeStamp = int(time.time()) + 24 * 60 * 60
            challenge.challengerReplay.CopyFrom(replay)
            challenge.vehicleStatus.vehicleId = replay.vehicle or "jeep"
            challenge.totalTries = 0
            challenge.totalWins = 0
            challenge.totalLosses = 0

        LOGGER.info(
            "[Challenges] Offered %s local challenges to player %s",
            len(out.Challenges),
            self.player_id,
        )
        return out

    def _handle_request_friends(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_FRIENDS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        friend_ids = PlayerDB.get_friends(self.player_id)
        for friend_id in friend_ids:
            profile = PlayerDB.load_player(friend_id)
            friend = out.PlayerInfos.add()
            friend.playerId = friend_id
            friend.playerName = profile.get("player_name") or profile.get("name") or friend_id
            friend.WCRank = float(profile.get("rank", 0.0))
            if profile.get("flag"):
                friend.flag = profile["flag"]
        LOGGER.info("[Friends] Returned %s friends for player %s", len(friend_ids), self.player_id)
        return out

    def _handle_request_player_infos(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_PLAYER_INFOS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        for player_id in in_msg.PlayerIds:
            if player_id == self.player_id:
                continue
            profile = PlayerDB.load_player(player_id)
            info = out.PlayerInfos.add()
            info.playerId = player_id
            info.playerName = profile.get("player_name") or profile.get("name") or player_id
            info.WCRank = float(profile.get("rank", 0.0))
            if profile.get("flag"):
                info.flag = profile["flag"]
        LOGGER.info("[Friends] Returned %s requested player profiles", len(out.PlayerInfos))
        return out

    def _handle_add_friends(self, in_msg):
        out = self._build_generic_ack(in_msg)
        player_ids = [player_id for player_id in in_msg.PlayerIds if player_id and player_id != self.player_id]
        if not player_ids:
            LOGGER.info("[Friends] Add request from %s contained no other player IDs", self.player_id)
            return out
        friends = PlayerDB.add_friends(self.player_id, player_ids)
        LOGGER.info("[Friends] Added %s friend IDs for player %s", len(player_ids), self.player_id)
        return out

    def _handle_remove_friend(self, in_msg):
        out = self._build_generic_ack(in_msg)
        target_id = in_msg.FriendInviteId or in_msg.PlayerId
        if target_id and target_id != self.player_id:
            PlayerDB.remove_friend(self.player_id, target_id)
            LOGGER.info("[Friends] Removed friend %s for player %s", target_id, self.player_id)
        else:
            LOGGER.info("[Friends] Remove request from %s had no target ID", self.player_id)
        return out

    def _handle_accept_invite(self, in_msg):
        out = self._build_generic_ack(in_msg)
        invite_id = in_msg.FriendInviteId
        if invite_id:
            PlayerDB.add_friends(self.player_id, [invite_id])
            PlayerDB.add_friends(invite_id, [self.player_id])
            LOGGER.info("[Friends] Accepted local invite between %s and %s", self.player_id, invite_id)
        else:
            LOGGER.warning("[Friends] Accept-invite request had no FriendInviteId")
        return out

    @staticmethod
    def _replay_sort_key(replay):
        """Sort valid results by farther distance, then faster time."""
        return (-replay.distance, replay.time, replay.playerId)

    def _best_player_replay(self, level_id):
        """Get this player's best valid saved replay for a level."""
        player_replays = [
            replay
            for replay in ghost_mgr.player_replays.get(level_id, [])
            if replay.playerId == self.player_id
            and replay.available
            and (replay.finishingStatus == 0 or replay.finishingStatus == 1)
        ]
        return min(player_replays, key=self._replay_sort_key, default=None)

    def _level_leaderboard_replays(self, level_id):
        """Return each player's best available result, ranked for the level."""
        best_by_player = {}
        for replay in ghost_mgr.player_replays.get(level_id, []):
            if (
                not replay.available
                or not replay.playerId
                or replay.finishingStatus not in (0, 1)
            ):
                continue
            current = best_by_player.get(replay.playerId)
            if current is None or self._replay_sort_key(replay) < self._replay_sort_key(current):
                best_by_player[replay.playerId] = replay
        return sorted(best_by_player.values(), key=self._replay_sort_key)

    def _leaderboard_replays_for_filter(self, level_id, leaderboard_filter):
        ranked = self._level_leaderboard_replays(level_id)
        filter_name = leaderboard_filter.lower()
        if filter_name in ("local", "default", "personal"):
            return [replay for replay in ranked if replay.playerId == self.player_id]
        if filter_name in ("friends", "friend"):
            friend_ids = set(PlayerDB.get_friends(self.player_id))
            friend_ids.add(self.player_id)
            return [replay for replay in ranked if replay.playerId in friend_ids]
        if filter_name in ("vehicle", "vehicles"):
            vehicle_id = self._requested_leaderboard_vehicle
            if vehicle_id:
                return [replay for replay in ranked if replay.vehicle == vehicle_id]
        return ranked

    def _handle_request_leaderboard(self, in_msg):
        """Return server-local standings scoped to the requested leaderboard filter."""
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_LEADERBOARD
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        level_id = in_msg.LevelId or "rookie_cup_01_01"
        leaderboard = out.Leaderboard
        leaderboard.levelId = level_id
        filter_name = in_msg.LeaderboardFilter if in_msg.HasField("LeaderboardFilter") else "global"
        leaderboard.leaderboardFilter = filter_name
        page_offset = max(0, in_msg.pageOffset)
        leaderboard.pageOffset = page_offset
        leaderboard.pageStartPosition = page_offset
        if in_msg.HasField("ReferenceTime"):
            leaderboard.referenceValue = in_msg.ReferenceTime

        self._requested_leaderboard_vehicle = in_msg.VehicleId if in_msg.HasField("VehicleId") else ""
        ranked_replays = self._leaderboard_replays_for_filter(level_id, filter_name)
        for replay in ranked_replays[page_offset : page_offset + 50]:
            profile = PlayerDB.load_player(replay.playerId)
            item = leaderboard.leaderboard.add()
            item.playerId = replay.playerId
            item.playerName = replay.playerName or profile.get("player_name") or profile.get("name") or replay.playerId
            item.levelId = level_id
            item.vehicleId = replay.vehicle or "jeep"
            item.time = replay.time
            item.distance = replay.distance
            item.finishingStatus = replay.finishingStatus
            item.replayId = replay._id if replay.HasField("_id") else ""
            item.flag = replay.flag
            item.sessionId = replay.sessionId
            item.retryCount = 0

        LOGGER.info(
            "[Leaderboard] Served %s ranked rows for %s (filter=%s vehicle=%s offset=%s)",
            len(leaderboard.leaderboard),
            level_id,
            filter_name,
            self._requested_leaderboard_vehicle or "all",
            page_offset,
        )
        return out

    def _handle_request_leaderboard_standings(self, in_msg):
        """Report the player's rank in global, local, and friends result sets."""
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_LEADERBOARD_STANDINGS
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber

        standings = out.LeaderboardStandings
        standings.levelId = in_msg.LevelId or "rookie_cup_01_01"
        out.LevelId = standings.levelId

        global_results = self._level_leaderboard_replays(standings.levelId)
        local_results = [r for r in global_results if r.playerId == self.player_id]
        friend_ids = set(PlayerDB.get_friends(self.player_id))
        friend_ids.add(self.player_id)
        friends_results = [r for r in global_results if r.playerId in friend_ids]

        def rank_of(results):
            return next(
                (rank for rank, replay in enumerate(results, start=1)
                 if replay.playerId == self.player_id),
                None,
            )

        global_rank = rank_of(global_results)
        local_rank = rank_of(local_results)
        friends_rank = rank_of(friends_results)
        standings.globalStandingValid = global_rank is not None
        standings.localStandingValid = local_rank is not None
        standings.friendsStandingValid = friends_rank is not None
        if global_rank is not None:
            standings.globalStanding = global_rank
        if local_rank is not None:
            standings.localStanding = local_rank
        if friends_rank is not None:
            standings.friendsStanding = friends_rank
        LOGGER.info(
            "[Leaderboard] Reported standings for %s: global=%s/%s local=%s/%s friends=%s/%s",
            standings.levelId,
            global_rank,
            len(global_results),
            local_rank,
            len(local_results),
            friends_rank,
            len(friends_results),
        )
        return out

    def _handle_request_boss_cup(self, in_msg):
        out = FSMessageCls()
        out.MessageType = MSG_REQUEST_BOSS_CUP
        out.ResponseCode = 0
        out.Session = self.session_id
        out.MessageNumber = in_msg.MessageNumber
        out.SendCupReplays = True

        profile = PlayerDB.load_player(self.player_id)
        player_rank = profile.get("rank", 20.0)

        cup_id = in_msg.CupId if in_msg.CupId else "hill_climb_cup"
        cups, wc = ghost_mgr.create_cup_matchmaking(
            cup_id,
            in_msg.VehicleId,
            in_msg.PValue,
            player_rank,
            in_msg.ContentVersion if in_msg.ContentVersion else 7,
            requester_player_id=self.player_id,
        )
        out.SendCupReplays = bool(cups)
        for c in cups:
            cp = out.Cups.add()
            cp.CopyFrom(c)
        out.WCRace.CopyFrom(wc)
        LOGGER.info("[BossCup] Served matchmaking for %s", cup_id)
        return out

    def _build_generic_ack(self, in_msg):
        out = FSMessageCls()
        out.MessageType = in_msg.MessageType if hasattr(in_msg, "MessageType") else 0
        out.ResponseCode = 0
        out.Session = self.session_id
        if hasattr(in_msg, "MessageNumber"):
            out.MessageNumber = in_msg.MessageNumber
        return out
