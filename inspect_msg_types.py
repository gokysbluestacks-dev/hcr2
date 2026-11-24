import urllib.request, json

def ida_call(name, args):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {'name': name, 'arguments': args}}).encode()
    req = urllib.request.Request('http://127.0.0.1:13337/mcp', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())['result']

for name, addr in [
    ('requestBossCup', '0x7d1090'),
    ('createCup', '0x7d6eb0'),
    ('requestReplays', '0x7ca020'),
    ('requestDivisionRaceReplays', '0x7ca4d0')
]:
    res = ida_call('decompile', {'addr': addr})
    if 'code' in res.get('structuredContent', {}):
        code = res['structuredContent']['code']
        # Find lines setting MessageType (e.g., [6] = )
        lines = [l.strip() for l in code.split('\n') if '[6] =' in l]
        print(f"{name} ({addr}): {lines}")
    else:
        print(f"{name}: Failed to decompile")
