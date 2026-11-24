import tempfile
import unittest
from unittest.mock import patch

from db import PlayerDB
from handlers import MessageDispatcher
from hcr2_proto import get_message_class

FSMessage = get_message_class("FSMessage")


class FriendHandlerTests(unittest.TestCase):
    def setUp(self):
        self.dispatcher = MessageDispatcher(0xABC123)
        self.dispatcher.player_id = "FriendTestPlayer"
        self.data_dir = tempfile.TemporaryDirectory()
        self.patch_data_dir = patch("db.DATA_DIR", self.data_dir.name)
        self.patch_data_dir.start()
        self.addCleanup(self.patch_data_dir.stop)
        self.addCleanup(self.data_dir.cleanup)

    def make_request(self, message_type, number=1):
        request = FSMessage()
        request.MessageType = message_type
        request.MessageNumber = number
        return request

    def test_add_and_request_friend_round_trip(self):
        PlayerDB.save_player("OtherPlayer", {
            "player_id": "OtherPlayer",
            "player_name": "Other Racer",
            "rank": 3.5,
            "friends": [],
        })
        request = self.make_request(50)
        request.PlayerIds.extend(["OtherPlayer", "OtherPlayer", "FriendTestPlayer"])

        response = self.dispatcher.handle(request)[0]
        self.assertEqual(response.ResponseCode, 0)
        self.assertEqual(PlayerDB.get_friends("FriendTestPlayer"), ["OtherPlayer"])

        response = self.dispatcher.handle(self.make_request(49))[0]
        self.assertEqual(len(response.PlayerInfos), 1)
        self.assertEqual(response.PlayerInfos[0].playerId, "OtherPlayer")
        self.assertEqual(response.PlayerInfos[0].playerName, "Other Racer")

    def test_request_player_infos_returns_only_requested_profiles(self):
        PlayerDB.save_player("OtherPlayer", {"player_id": "OtherPlayer", "rank": 2.0})
        request = self.make_request(53)
        request.PlayerIds.extend(["OtherPlayer", "FriendTestPlayer"])

        response = self.dispatcher.handle(request)[0]

        self.assertEqual(response.MessageType, 53)
        self.assertEqual(len(response.PlayerInfos), 1)
        self.assertEqual(response.PlayerInfos[0].playerId, "OtherPlayer")

    def test_remove_friend_and_accept_invite(self):
        PlayerDB.add_friends("FriendTestPlayer", ["OtherPlayer"])
        request = self.make_request(52)
        request.FriendInviteId = "OtherPlayer"
        self.dispatcher.handle(request)
        self.assertEqual(PlayerDB.get_friends("FriendTestPlayer"), [])

        request = self.make_request(48)
        request.FriendInviteId = "OtherPlayer"
        self.dispatcher.handle(request)
        self.assertEqual(PlayerDB.get_friends("FriendTestPlayer"), ["OtherPlayer"])
        self.assertEqual(PlayerDB.get_friends("OtherPlayer"), ["FriendTestPlayer"])


if __name__ == "__main__":
    unittest.main()
