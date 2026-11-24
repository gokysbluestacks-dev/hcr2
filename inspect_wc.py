import urllib.request, json

def ida_call(name, args):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {'name': name, 'arguments': args}}).encode()
    req = urllib.request.Request('http://127.0.0.1:13337/mcp', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        r = json.loads(resp.read().decode())['result']
        if 'content' in r and len(r['content']) > 0:
            return json.loads(r['content'][0]['text'])
        return r

code = """
import idc
cur = 0x803a40
lines = []
while cur < 0x803c20:
    d = idc.GetDisasm(cur)
    lines.append(f"{hex(cur)}: {d}")
    cur = idc.next_head(cur)
print("\\n".join(lines[:40]))
"""

res = ida_call('py_eval', {'code': code})
print(res.get('stdout'))
if res.get('stderr'):
    print("ERR:", res.get('stderr'))
