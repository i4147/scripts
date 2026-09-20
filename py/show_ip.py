import socket
import urllib.request


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "Unable to get local IP"


def get_public_ip():
    try:
        url = "https://ipify.org"
        req = urllib.request.urlopen(url, timeout=5)
        return req.read().decode("utf-8")
    except Exception:
        return "Unable to get public IP"


if __name__ == "__main__":
    print("Local IP:", get_local_ip())
    print("Public IP:", get_public_ip())
