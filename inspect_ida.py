import urllib.request, json

def ida_call(name, args):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {'name': name, 'arguments': args}}).encode()
    req = urllib.request.Request('http://127.0.0.1:13337/mcp', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())['result']

code = """
import idc, idautils, ida_bytes

dispatch_strings = [
    'teamMgmt', 'updateChallenge', 'createCup', 'acceptInvite', 'addFriends',
    'removeFriends', 'seasonReset', 'setTestGroup', 'storeReplay', 'requestFlag',
    'createNewChallenge', 'createTeam', 'inviteFriend', 'requestReplays',
    'requestDivisionRaceReplays', 'requestWcRaceReplays', 'getTournamentStatus',
    'getAvailableTournaments', 'getGameParameters', 'getDivisionStatus',
    'requestLeaderboard', 'requestLeaderboardStandings', 'requestChallenges',
    'requestCups', 'requestBossCup', 'StoreGameStatus', 'requestGameStatus',
    'requestTeams', 'requestFriendlyRaces', 'requestPlayerInfos', 'requestFriends'
]

# For each dispatch string, find xrefs and print callers
for s in idautils.Strings():
    text = str(s)
    for ds in dispatch_strings:
        if f"dispatch {ds}" in text:
            for xref in idautils.XrefsTo(s.ea):
                func = idaapi.get_func(xref.frm)
                fname = idc.get_func_name(xref.frm) if func else "unknown"
                print(f"{ds:28s} -> {hex(xref.frm)} in {fname}")
"""

res = ida_call('py_eval', {'code': code})
print(res.get('structuredContent', {}).get('stdout', res))
