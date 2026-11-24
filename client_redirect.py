"""
Hill Climb Racing 2 - Hosts and Frida Redirection Generator
Configured with exact hosts discovered in server.json (Azure eastus cloudapp & vtesting).
"""

import ipaddress
import sys

HOSTS_ENTRIES = """# HCR2 Private Server Redirection Entries
%(server_ip)s arg1f0.eastus.cloudapp.azure.com
%(server_ip)s arg1f1.eastus.cloudapp.azure.com
%(server_ip)s arg1f2.eastus.cloudapp.azure.com
%(server_ip)s arg1f3.eastus.cloudapp.azure.com
%(server_ip)s arg1f4.eastus.cloudapp.azure.com
%(server_ip)s arg1f5.eastus.cloudapp.azure.com
%(server_ip)s arg1f6.eastus.cloudapp.azure.com
%(server_ip)s arg1f7.eastus.cloudapp.azure.com
%(server_ip)s vtesting.cloudapp.net
%(server_ip)s playhcr.com
%(server_ip)s monitor.fingersoft.net
"""

FRIDA_HOOK = """// Frida Hook for HCR2 Server Redirection
const SERVER_IP = "%(server_ip)s";
const SERVER_PORT = %(server_port)d;

const TARGET_HOSTS = [
    "eastus.cloudapp.azure.com",
    "vtesting.cloudapp.net",
    "playhcr.com",
    "fingersoft.net"
];

Java.perform(function () {
    try {
        var AppActivity = Java.use("com.fingersoft.hcr2.AppActivity");
        AppActivity.getAccountServerAddress.implementation = function () {
            var target = "http://" + SERVER_IP + ":" + SERVER_PORT;
            console.log("Redirected getAccountServerAddress() -> " + target);
            return target;
        };
    } catch (e) {}
});

Interceptor.attach(Module.findExportByName(null, "getaddrinfo"), {
    onEnter: function (args) {
        var host = args[0].readUtf8String();
        if (host) {
            for (var i = 0; i < TARGET_HOSTS.length; i++) {
                if (host.indexOf(TARGET_HOSTS[i]) !== -1) {
                    console.log("Redirecting DNS: " + host + " -> " + SERVER_IP);
                    args[0].writeUtf8String(SERVER_IP);
                    break;
                }
            }
        }
    }
});
"""

def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python client_redirect.py <server-ipv4> [port]")
    try:
        ip = str(ipaddress.IPv4Address(sys.argv[1]))
    except ipaddress.AddressValueError as exc:
        raise SystemExit("server-ipv4 must be a numeric IPv4 address") from exc

    port = int(sys.argv[2]) if len(sys.argv) > 2 else 22994
    if not 1 <= port <= 65535:
        raise SystemExit("port must be between 1 and 65535")

    with open("hosts_entries.txt", "w", encoding="utf-8") as f:
        f.write(HOSTS_ENTRIES % {"server_ip": ip})

    with open("redirect.js", "w", encoding="utf-8") as f:
        f.write(FRIDA_HOOK % {"server_ip": ip, "server_port": port})

    print(f"Generated hosts entries -> hosts_entries.txt")
    print(f"Generated Frida script -> redirect.js (Port {port})")

if __name__ == "__main__":
    main()
