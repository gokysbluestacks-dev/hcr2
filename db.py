"""
Hill Climb Racing 2 - Database / Profile Storage
Manages persistence of player game status, currencies, unlocks, and garage upgrades.
"""

import json
import os
import time

DATA_DIR = os.path.expanduser(os.environ.get(
    "HCR2_DATA_DIR", os.path.join(os.path.dirname(__file__), "player_data")
))
os.makedirs(DATA_DIR, exist_ok=True)

# Authentic HCR2 v1.5.1 (May 20, 2017) vehicle roster from gamedata.json
DEFAULT_VEHICLES = [
    "Jeep", "Scooter", "SuperJeep", "Motocross", "SportsCar", 
    "MonsterTruck", "SuperDiesel", "Tank", "Formula"
]

DEFAULT_WORLDS = [
    "Countryside", "Forest", "City", "Mountain", "RustbucketReef",
    "Winter", "Mines", "Desert", "Beach", "Bog", "Gloomvale"
]

class PlayerDB:
    @staticmethod
    def get_player_path(player_id: str) -> str:
        safe_id = "".join(c for c in player_id if c.isalnum() or c in "-_") or "default_player"
        return os.path.join(DATA_DIR, f"{safe_id}.json")

    @classmethod
    def iter_players(cls):
        """Yield valid player profiles persisted in the local data directory."""
        if not os.path.isdir(DATA_DIR):
            return
        for filename in os.listdir(DATA_DIR):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(DATA_DIR, filename)
            try:
                with open(path, "r", encoding="utf-8") as profile_file:
                    profile = json.load(profile_file)
                player_id = profile.get("player_id")
                if player_id:
                    yield player_id, profile
            except (OSError, json.JSONDecodeError):
                continue

    @classmethod
    def load_player(cls, player_id: str) -> dict:
        path = cls.get_player_path(player_id)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading profile {path}: {e}")

        # Keep new profiles empty/low rather than inventing advanced progress.
        default_profile = {
            "player_id": player_id,
            "friends": [],
            "coins": 0,
            "diamonds": 0,
            "xp": 0,
            "rank": 0.0,
            "cloud_save_version": 0,
            "vehicles": ["jeep"],
            "worlds": ["countryside_01"],
            "unlocks": [],
            "last_login": int(time.time()),
        }
        cls.save_player(player_id, default_profile)
        return default_profile

    @classmethod
    def save_player(cls, player_id: str, data: dict):
        path = cls.get_player_path(player_id)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving player {player_id}: {e}")

    @classmethod
    def get_friends(cls, player_id: str) -> list[str]:
        profile = cls.load_player(player_id)
        friends = profile.get("friends", [])
        return [friend_id for friend_id in friends if isinstance(friend_id, str) and friend_id != player_id]

    @classmethod
    def add_friends(cls, player_id: str, friend_ids: list[str]) -> list[str]:
        profile = cls.load_player(player_id)
        friends = cls.get_friends(player_id)
        for friend_id in friend_ids:
            if isinstance(friend_id, str) and friend_id and friend_id != player_id and friend_id not in friends:
                friends.append(friend_id)
        profile["friends"] = friends
        cls.save_player(player_id, profile)
        return friends

    @classmethod
    def remove_friend(cls, player_id: str, friend_id: str) -> list[str]:
        profile = cls.load_player(player_id)
        friends = [item for item in cls.get_friends(player_id) if item != friend_id]
        profile["friends"] = friends
        cls.save_player(player_id, profile)
        return friends

    @classmethod
    def update_from_game_status(cls, player_id: str, game_status_msg):
        """Updates internal profile from incoming Protobuf GameStatus message."""
        profile = cls.load_player(player_id)
        # Proto2 scalar fields have useful presence information. Preserve explicit
        # zero values (e.g. a new player's WCRank) instead of keeping stale defaults.
        for field, key in (
            ("totalCoinsCollected", "coins"),
            ("diamonds", "diamonds"),
            ("playerXp", "xp"),
            ("WCRank", "rank"),
        ):
            if game_status_msg.HasField(field):
                profile[key] = getattr(game_status_msg, field)

        if game_status_msg.HasField("cloudSaveVersion"):
            profile["cloud_save_version"] = game_status_msg.cloudSaveVersion + 1

        # Persist the flag the player picked so requestFlag can echo it back
        # instead of re-resolving the country from their IP.
        if game_status_msg.HasField("flag"):
            profile["flag"] = game_status_msg.flag

        profile["vehicles"] = list(game_status_msg.unlockedVehicles)
        profile["worlds"] = list(game_status_msg.ownedWorlds)
        profile["unlocks"] = [
            {"type": item.type, "id": item.id,
             "unlockState": item.unlockState, "unlockType": item.unlockType}
            for item in game_status_msg.unlocks
        ]

        profile["last_login"] = int(time.time())
        cls.save_player(player_id, profile)
        return profile
