import urllib.request, json

def ida_call(name, args):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {'name': name, 'arguments': args}}).encode()
    req = urllib.request.Request('http://127.0.0.1:13337/mcp', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())['result']

code = """
import idc
for ea in range(0x819470, 0x819515):
    d = idc.GetDisasm(ea)
    if d:
        print(f"{hex(ea)}: {d}")
"""

res = ida_call('py_eval', {'code': code})
print(res.get('structuredContent', {}).get('stdout', res))
