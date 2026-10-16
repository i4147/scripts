#!/data/data/com.termux/files/usr/bin/env python

import sys
import time

import requests


def get_connection_info():
    try:
        response = requests.get("http://ip-api.com/json/", timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return {
                "ip": data.get("query"),
                "country": data.get("country"),
                "city": data.get("city"),
                "isp": data.get("isp"),
                "region": data.get("regionName"),
            }
        else:
            print("Error: Failed to retrieve location data.")
            return None

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to IP service: {e}")
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
    try:
        while True:
            info = get_connection_info()
            print_info(info)
            time.sleep(7)
    except KeyboardInterrupt:
        print("\nProcess stopped by user.")
        sys.exit(0)
