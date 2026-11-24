# HCR2 Private Server

Python implementation of a private HCR2-compatible game server. Development may use an Android emulator; the deployed service does not require ADB, IDA, Docker, or an emulator.

## Local client routing

For a client on the same LAN, generate the mapping with the server's reachable IPv4 and port, for example:

```powershell
python client_redirect.py 192.168.5.16 22994
```

This only generates `hosts_entries.txt` and `redirect.js`; it does not apply either one. Apply the hosts mapping on the device running the game, or load the Frida hook into that game process. Editing the server computer's hosts file does not redirect an Android client. The client may still display `playhcr.com`; DNS redirection changes the destination IP, not the hostname shown by the app. Confirm routing by checking that the private server logs the client's connection and challenge request.

## Windows Server deployment

This server listens on **TCP 22994** by default. The game protocol uses raw TCP, not HTTP.

### 1. Prepare Windows Server

1. Install Python 3.11 x64 from python.org. In the installer, select **Add Python to PATH**.
2. Create a deployment folder, for example `C:\\HCR2Server`, and copy the project files to it.
3. Place the version-matched `libcocos2dcpp.so` in `C:\\HCR2Server\\runtime-lib\\libcocos2dcpp.so`. This file is needed by the current protobuf schema loader at startup.
4. Put the compatible decrypted configuration JSON files in `C:\\HCR2Server\\production-config\\`. At minimum, add `gamedata.json`, `economy.json`, `events_rank.json`, and `tournaments.json`.
5. Use only binaries/configuration/assets you are authorized to run and host.

### 2. Install Python dependencies

Open PowerShell as the account that will run the service:

```powershell
Set-Location C:\\HCR2Server
py -3.11 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, you can skip activation and run `C:\\HCR2Server\\.venv\\Scripts\\python.exe` directly in the commands below.

### 3. Configure and test the server

Set environment variables for this PowerShell session and launch it in the foreground:

```powershell
$env:HCR2_HOST = "0.0.0.0"
$env:HCR2_PORT = "22994"
$env:HCR2_SO_PATH = "C:\\HCR2Server\\runtime-lib\\libcocos2dcpp.so"
$env:HCR2_DECRYPTED_DIR = "C:\\HCR2Server\\production-config"
$env:HCR2_DATA_DIR = "C:\\HCR2Server\\player_data"
$env:HCR2_LOG_FILE = "C:\\HCR2Server\\logs\\server.log"
$env:HCR2_LOG_LEVEL = "INFO"
python run_server.py
```

The launcher logs to the console and a rotating log file (10 MB per file, five backups). Confirm it reports that it is listening. Stop the foreground test with Ctrl+C.

### 4. Open the Windows firewall

Run PowerShell as Administrator:

```powershell
New-NetFirewallRule -DisplayName "HCR2 game server TCP 22994" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22994
```

Also allow inbound TCP 22994 in the hosting provider's cloud firewall/security group. Test from a different network; a successful local connection alone does not prove the public route works.

### 5. Point your domain to the server

At your DNS provider, create an `A` record for the hostname the client will use, pointing to the server's **public IPv4**. Add an `AAAA` record only if the server has a working public IPv6 address and its firewall allows the traffic. Wait for DNS to propagate.

DNS only maps a name to an address; it does not translate ports. The game/client configuration must use the hostname and TCP port **22994**. Confirm the version of the client accepts your server hostname/port configuration. Do not change or bypass APK signature validation as a way to force an incompatible package to run.

### 6. Keep it running after sign-out/reboot

For an initial setup, Task Scheduler can start the server at boot under a dedicated Windows account:

1. Create a local account such as `HCR2Svc` and grant it read/execute access to the app/config/library directories and modify access only to `player_data` and `logs`.
2. Create a task triggered **At startup**, set **Run whether user is logged on or not**, and configure **Start in** as `C:\\HCR2Server`.
3. Set the program to `C:\\HCR2Server\\.venv\\Scripts\\python.exe` and arguments to `run_server.py --host 0.0.0.0 --port 22994 --log-file C:\\HCR2Server\\logs\\server.log`.
4. In task settings, enable restart on failure and set an appropriate retry interval.
5. Start the task and inspect `logs\\server.log` and Task Scheduler's last-run result.

Back up `player_data` regularly. Do not run the server with Administrator privileges unless required.

## Logs and troubleshooting

- Default log file: `server.log` in the current working directory. Set `HCR2_LOG_FILE` or pass `--log-file` to choose another path.
- Set `HCR2_LOG_LEVEL=DEBUG` for packet details during local diagnosis; return to `INFO` afterward because debug logs can be large and include player identifiers.
- Check the application log, Windows Firewall rule, provider firewall, DNS resolution, and that the process owns TCP 22994.
- CGNAT prevents unsolicited connections to a home-hosted server. A DNS record does not bypass CGNAT; use a host with a public IP or ask the ISP for a public address.

## Security and compatibility limitations

The protocol uses legacy XOR framing, not modern encryption or client authentication. This is experimental software, not a hardened public service. Restrict access to trusted clients and do not store sensitive information. Hill Climb Cup matchmaking refers to ghost files in the client's local cache; a remote server cannot install files into Android's private app directory. A modified APK may also fail client-side signature validation.

## Tests

```powershell
python -m unittest test_leaderboards test_ghost_manager
python test_e2e.py
```
