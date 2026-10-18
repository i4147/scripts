#!/data/data/com.termux/files/usr/bin/python

from __future__ import annotations
import sys
import time

import requests


def get_connection_info():
    backends = [
        {
            "name": "ip-api.com",
            "url": "http://ip-api.com",
            "parser": lambda d: (
                {
                    "ip": d.get("query"),
                    "country": d.get("country"),
                    "city": d.get("city"),
                    "isp": d.get("isp"),
                    "region": d.get("regionName"),
                }
                if d.get("status") == "success"
                else None
            ),
        },
        {
            "name": "ipapi.co",
            "url": "https://ipapi.co",
            "parser": lambda d: (
                {
                    "ip": d.get("ip"),
                    "country": d.get("country_name"),
                    "city": d.get("city"),
                    "isp": d.get("org"),
                    "region": d.get("region"),
                }
                if "error" not in d
                else None
            ),
        },
        {
            "name": "ipwho.is",
            "url": "https://ipwho.is",
            "parser": lambda d: (
                {
                    "ip": d.get("ip"),
                    "country": d.get("country"),
                    "city": d.get("city"),
                    "isp": d.get("connection", {}).get("isp"),
                    "region": d.get("region"),
                }
                if d.get("success") is True
                else None
            ),
        },
    ]
    for backend in backends:
        try:
            response = requests.get(backend["url"], timeout=5)
            response.raise_for_status()
            data = response.json()
            info = backend["parser"](data)
            if info:
                return info
            else:
                print(f"[{backend['name']}] Data parsing error or API error response.")
        except requests.exceptions.RequestException as e:
            print(f"[{backend['name']}] Connection failed: {e}")
            continue
    print("All IP service backends failed. Network might be down.")
    return None


def print_info(info):
    if info:
        print("-" * 30)
        print(f"IP Address: {info['ip']}")
        print(f"Location:   {info['city']}, {info['region']}, {info['country']}")
        print(f"ISP:        {info['isp']}")
        print("-" * 30)
    else:
        print("Could not retrieve connection details.")


if __name__ == "__main__":
    normal_delay = 7
    cooldown_delay = 30
    try:
        while True:
            info = get_connection_info()
            print_info(info)
            if info:
                time.sleep(normal_delay)
            else:
                print(f"Entering {cooldown_delay}-second cooldown to preserve API rate limits...")
                time.sleep(cooldown_delay)
    except KeyboardInterrupt:
        print("\nProcess stopped by user.")
        sys.exit(0)
