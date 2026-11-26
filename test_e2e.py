"""
End-to-End Integration Test for HCR2 Private Server Emulator.
Simulates a live game client connecting, completing handshake, fetching parameters, loading & saving progress.
"""

import asyncio
import struct
import time
from hcr2_proto import get_message_class
from cipher import HCR2Framer
from server import HCR2PrivateServer
from db import PlayerDB
from ghost_manager import ghost_mgr
from handlers import cup_finish_ranks

FSMessageCls = get_message_class("FSMessage")

async def run_test():
    host = "127.0.0.1"
    port = 10081 # Use 10081 for unit testing to avoid conflicts

    # Seed a representative test profile without changing real player data.
    PlayerDB.save_player("TestPilot99", {
        "player_id": "TestPilot99",
        "coins": 1234567,
        "diamonds": 88888,
        "xp": 15000,
        "rank": 0.0,
        "cloud_save_version": 1,
        "vehicles": ["jeep", "monowheel"],
        "worlds": ["countryside_01"],
        "unlocks": [],
    })

    # 1. Start server in background task
    server = HCR2PrivateServer(host, port)
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.5)

    print("[*] Connecting simulated client to server...")
    reader, writer = await asyncio.open_connection(host, port)
    framer = HCR2Framer()

    async def send_msg(msg):
        pkt = framer.pack_message(msg)
        writer.write(pkt)
        await writer.drain()

    async def recv_msg():
        # Read 4-byte header
        hdr_bytes = await reader.readexactly(4)
        dec_hdr = framer.decrypt_bytes(hdr_bytes)
        payload_len = struct.unpack(">I", dec_hdr)[0]

        # Read payload
        payload_bytes = await reader.readexactly(payload_len)
        dec_payload = framer.decrypt_bytes(payload_bytes)

        res = FSMessageCls()
        res.ParseFromString(dec_payload)
        return res

    # 2. Test Handshake (MessageType = 1)
    print("\n--- TEST 1: HANDSHAKE ---")
    hs = FSMessageCls()
    hs.MessageType = 1
    hs.HandshakeMessage = "HCR2_TEST_CLIENT_BUILD"
    hs.Version.append(200)
    hs.Platform = "Android"
    await send_msg(hs)

    resp_hs = await recv_msg()
    print(f"[Client] Received Handshake Response: MessageType={resp_hs.MessageType}, ResponseCode={resp_hs.ResponseCode}, Session=0x{resp_hs.Session:X}")
    assert resp_hs.MessageType == 1
    assert resp_hs.ResponseCode == 0
    assert resp_hs.Session != 0
    session_id = resp_hs.Session

    # 3. Test GameParameters (MessageType = 11)
    print("\n--- TEST 2: GET GAME PARAMETERS ---")
    gp_req = FSMessageCls()
    gp_req.MessageType = 11
    gp_req.Session = session_id
    await send_msg(gp_req)

    resp_gp = await recv_msg()
    print(f"[Client] Received GameParameters: serverTime={resp_gp.GameParameters.serverTime}, jsonObjects={len(resp_gp.GameParameters.jsonObjects)}")
    assert resp_gp.MessageType == 11
    assert resp_gp.GameParameters.serverTime > 0
    assert len(resp_gp.GameParameters.jsonObjects) > 0

    # 4. Test Request GameStatus (MessageType = 40)
    print("\n--- TEST 3: REQUEST GAME STATUS (LOAD PROFILE) ---")
    status_req = FSMessageCls()
    status_req.MessageType = 40
    status_req.Session = session_id
    status_req.PlayerId = "TestPilot99"
    await send_msg(status_req)

    resp_status = await recv_msg()
    gs = resp_status.GameStatus
    print(f"[Client] Received GameStatus: Coins={gs.totalCoinsCollected}, Gems={gs.diamonds}, Vehicles={list(gs.unlockedVehicles)}")
    assert resp_status.MessageType == 40
    assert gs.totalCoinsCollected >= 1000000
    assert len(gs.unlockedVehicles) > 0

    # 5. Test Store GameStatus (MessageType = 39)
    print("\n--- TEST 4: STORE GAME STATUS (SAVE PROFILE) ---")
    save_req = FSMessageCls()
    save_req.MessageType = 39
    save_req.Session = session_id
    save_req.PlayerId = "TestPilot99"
    save_req.GameStatus.playerId = "TestPilot99"
    save_req.GameStatus.playerName = "TestPilot99"
    save_req.GameStatus.totalCoinsCollected = 1234567
    save_req.GameStatus.diamonds = 88888
    save_req.GameStatus.playerXp = 15000
    await send_msg(save_req)

    resp_save = await recv_msg()
    print(f"[Client] Received StoreGameStatus ACK: ResponseCode={resp_save.ResponseCode}")
    assert resp_save.ResponseCode == 0

    # Verify persisted in database
    saved_profile = PlayerDB.load_player("TestPilot99")
    print(f"[DB] Verified saved profile: Coins={saved_profile['coins']}, Diamonds={saved_profile['diamonds']}")
    assert saved_profile['coins'] == 1234567
    assert saved_profile['diamonds'] == 88888

    # 6. Test Request Cups (MessageType = 31) - UI Menu
    print("\n--- TEST 5: REQUEST CUPS (UI LIST) ---")
    cup_req = FSMessageCls()
    cup_req.MessageType = 31
    cup_req.Session = session_id
    await send_msg(cup_req)

    resp_cup = await recv_msg()
    print(f"[Client] Received Cups for UI: Total={len(resp_cup.Cups)}")
    assert resp_cup.MessageType == 31
    assert len(resp_cup.Cups) == 20

    # 7. Test Cup Matchmaking (MessageType = 31) - Hill Climb Cup
    print("\n--- TEST 6: CUP MATCHMAKING (HILL CLIMB CUP) ---")
    match_req = FSMessageCls()
    match_req.MessageType = 31
    match_req.Session = session_id
    match_req.PlayerId = "TestPilot99"
    match_req.CupId = "hill_climb_cup"
    match_req.VehicleId = "jeep"
    match_req.PValue = 4.0
    match_req.ContentVersion = 7
    match_req.IsRanked = False
    await send_msg(match_req)

    resp_match = await recv_msg()
    print(f"[Client] Received Matchmaking: Opponents={len(resp_match.Cups)}, SendCupReplays={resp_match.SendCupReplays}")
    assert resp_match.MessageType == 31
    assert len(resp_match.Cups) <= 3
    assert resp_match.SendCupReplays is bool(resp_match.Cups)
    expected_replay_ids = [
        replay_id for cup in resp_match.Cups for replay_id in cup.replayIds
    ]
    first_leg_replay_ids = [cup.replayIds[0] for cup in resp_match.Cups]
    assert [replay._id for replay in resp_match.WCRace.Replays] == first_leg_replay_ids
    resolved = [ghost_mgr.get_cup_replays([rid]) for rid in expected_replay_ids]
    assert all(resolved)
    # Matchmaking prefers the requested vehicle but falls back to any vehicle
    # when there aren't enough same-vehicle opponents cached, so only require
    # the request to be honoured where such ghosts actually exist.
    assert any(rep[0].vehicle == "jeep" for rep in resolved)
    assert len(resp_match.WCRace.RaceFinishWCRanks) == len(cup_finish_ranks(0.0))
    assert len(resp_match.WCRace.Replays) == len(resp_match.Cups)
    opponent_owners = []
    replay_offset = 0
    for opp in resp_match.Cups:
        assert opp.cupId == "hill_climb_cup"
        assert len(opp.replayIds) == 2
        assert all(ghost_mgr.get_cup_replays([rid]) for rid in opp.replayIds)
        opponent_replay = resp_match.WCRace.Replays[replay_offset]
        opponent_owner = opponent_replay.playerId
        assert opponent_owner != "TestPilot99"
        assert opponent_owner == ghost_mgr.get_cup_replays([opp.replayIds[0]])[0].playerId
        opponent_owners.append(opponent_owner)
        replay_offset += 1
    assert len(set(opponent_owners)) == len(opponent_owners)

    # 8. Test Store Replay (MessageType = 2)
    print("\n--- TEST 7: STORE REPLAY ---")
    rep_req = FSMessageCls()
    rep_req.MessageType = 2
    rep_req.Session = session_id
    rep_req.PlayerId = "TestPilot99"
    r = rep_req.Replay
    r.playerId = "TestPilot99"
    r.playerName = "TestPilot99"
    r.available = True
    r.vehicle = "jeep"
    r.levelId = "rookie_cup_01_01"
    r.time = 24.5
    r.zippedFrameData = b"test_frame_stream"
    await send_msg(rep_req)

    resp_rep = await recv_msg()
    print(f"[Client] Received StoreReplay ACK: ResponseCode={resp_rep.ResponseCode}, Key={resp_rep.Key}")
    assert resp_rep.ResponseCode == 0
    assert len(resp_rep.Key) > 0

    # 9. Test Request WC Race Replays (MessageType = 21)
    print("\n--- TEST 8: REQUEST WC RACE REPLAYS ---")
    wc_req = FSMessageCls()
    wc_req.MessageType = 21
    wc_req.Session = session_id
    wc_req.VehicleId = "jeep"
    wc_req.PValue = 4.0
    next_leg_ids = [cup.replayIds[1] for cup in resp_match.Cups]
    wc_req.LevelId = ghost_mgr.get_cup_replays([next_leg_ids[0]])[0].levelId
    wc_req.ReplayIds.extend(next_leg_ids)
    await send_msg(wc_req)

    resp_wc = await recv_msg()
    print(f"[Client] Received WC Race Replays: Count={len(resp_wc.WCRace.Replays)}")
    assert resp_wc.MessageType == 21
    assert len(resp_wc.WCRace.Replays) == len(wc_req.ReplayIds)
    assert [r.playerId for r in resp_wc.WCRace.Replays] == [
        ghost_mgr.get_cup_replays([rid])[0].playerId
        for rid in wc_req.ReplayIds
    ]
    assert all(replay.byteFrameData for replay in resp_wc.WCRace.Replays)
    assert all(not replay.zippedFrameData for replay in resp_wc.WCRace.Replays)

    # Cleanup
    writer.close()
    await writer.wait_closed()
    server_task.cancel()
    print("\n[+] ALL END-TO-END TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_test())
