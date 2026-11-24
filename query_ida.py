import urllib.request, json

def ida_call(name, args):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {'name': name, 'arguments': args}}).encode()
    req = urllib.request.Request('http://127.0.0.1:13337/mcp', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())['result']

res = ida_call('func_query', {'queries': [{'filter': '*GameProtocolLayer*'}]})
data = json.loads(res['content'][0]['text'])
for fn in data[0]['data']:
    print(fn['addr'], fn['name'])
