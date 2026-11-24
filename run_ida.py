import urllib.request, json, sys

def run_ida_py(code):
    payload = json.dumps({'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {'name': 'py_eval', 'arguments': {'code': code}}}).encode()
    req = urllib.request.Request('http://127.0.0.1:13337/mcp', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        r = json.loads(resp.read().decode())['result']
        if 'content' in r and len(r['content']) > 0:
            parsed = json.loads(r['content'][0]['text'])
            if parsed.get('stdout'):
                print(parsed['stdout'])
            if parsed.get('stderr'):
                print("ERR:", parsed['stderr'])
            if parsed.get('result') and parsed['result'] != "None":
                print("RES:", parsed['result'])
        else:
            print("RAW:", r)

if __name__ == '__main__':
    with open(sys.argv[1], 'r') as f:
        code = f.read()
    run_ida_py(code)
