from __future__ import annotations

import json
import shutil
import socket
import subprocess
import urllib.request
from typing import Any


def run_command(*args: str) -> str:
    if shutil.which(args[0]) is None:
        return f"{args[0]} is not installed"

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return f"Unable to run {' '.join(args)}: {error}"

    output = result.stdout.strip()

    if result.returncode != 0:
        error = result.stderr.strip() or "unknown error"
        return f"Command failed: {error}"

    return output or "(no output)"


def get_public_ip() -> str:
    services = (
        "https://api.ipify.org?format=json",
        "https://ifconfig.me/ip",
    )

    for url in services:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                data = response.read().decode().strip()

            if data.startswith("{"):
                parsed: dict[str, Any] = json.loads(data)
                return str(parsed.get("ip", "Unknown"))

            return data

        except Exception:
            continue

    return "Unable to determine public IP"


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    except OSError as error:
        return f"Unable to determine local IP: {error}"


def get_dns_info() -> str:
    try:
        addresses = socket.getaddrinfo(
            "example.com",
            443,
            type=socket.SOCK_STREAM,
        )

        unique_addresses = sorted({address[4][0] for address in addresses})

        return ", ".join(unique_addresses)

    except socket.gaierror as error:
        return f"DNS lookup failed: {error}"


def main() -> None:
    print("Network information")
    print("===================")
    print(f"Public IP:       {get_public_ip()}")
    print(f"Local IP:        {get_local_ip()}")
    print(f"Hostname:        {socket.gethostname()}")
    print(f"DNS resolution:  {get_dns_info()}")

    print("\nNetwork interfaces")
    print("==================")
    print(run_command("ip", "-br", "addr"))

    print("\nDefault gateway")
    print("================")
    print(run_command("ip", "route", "show", "default"))


if __name__ == "__main__":
    main()
