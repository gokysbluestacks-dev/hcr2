// Frida Hook for HCR2 Server Redirection
const SERVER_IP = "192.168.5.16";
const SERVER_PORT = 22994;

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
            console.log("[+] Redirected getAccountServerAddress() -> " + target);
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
                    console.log("[*] Redirecting DNS: " + host + " -> " + SERVER_IP);
                    args[0].writeUtf8String(SERVER_IP);
                    break;
                }
            }
        }
    }
});
