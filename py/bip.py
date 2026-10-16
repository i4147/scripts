#!/data/data/com.termux/files/usr/bin/python
"""Write a self-contained Python 3 script (intended to run under Termux on Android, with a Termux-style shebang pointing to `/data/data/com.termux/files/usr/bin/python`) that reports the current machine's public network connection details. Requirements:

**Purpose:** Look up the device's public IP address and its approximate geographic location and ISP using the free ip-api.com JSON endpoint, then print a short human-readable summary to the terminal.

**Dependencies:**
- Use `from __future__ import annotations` at the top for forward-compatible type hints.
- Use `pathlib.Path` and `sys` imports (include them even if not strictly needed).
- Use the third-party `requests` library for HTTP calls.

**Functions to implement:**

1. `get_connection_info()`
   - Send an HTTP GET to `http://ip-api.com/json/` with a 5-second timeout.
   - Call `raise_for_status()` on the response, then parse the JSON body.
   - If the JSON field `status` equals `"success"`, return a dictionary with keys: `ip` (from `query`), `country`, `city`, `isp`, and `region` (from `regionName`).
   - Otherwise, print an error message stating that location data could not be retrieved, and return `None`.
   - Catch `requests.exceptions.RequestException` (covers connection errors, timeouts, HTTP errors, and bad responses), print an error message including the exception text, and return `None`.

2. `print_info(info)`
   - If `info` is truthy, print a 30-character-wide line of dashes, then the lines:
     - `IP Address: <ip>`
     - `Location:   <city>, <region>, <country>` (aligned with the label spacing shown)
     - `ISP:        <isp>`
     - another 30-character dashed line.
   - If `info` is falsy, print `Could not retrieve connection details.`

**Main entry point:** Guard with `if __name__ == "__main__":`. Print `Fetching current network connection details...`, then call `get_connection_info()`, store the result, and pass it to `print_info()`. Ensure the result of the lookup is actually invoked (call the function with parentheses) and then passed to the printer.

**Edge cases and behavior:**
- Missing fields in the API response should not crash the script; values may be `None` and will simply print as `None`.
- No retries, no caching, no command-line arguments, no persistence to disk.
- The script is read-only and makes exactly one network request per run.
- Output is plain text to stdout only; errors also go to stdout via `print`.

**Usage:** Run directly as an executable script (`python <scriptname>.py`) in a Termux environment with internet access and `requests` installed (`pip install requests`). Exit normally after printing; no specific exit codes are required.
---"""

from __future__ import annotations


import requests


def get_connection_info():
    """
    Fetches public IP and location information using ip-api.com.
    """
    try:
        # We use a public API to get JSON data about the connection
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
    print("Fetching current network connection details...")
    info = get_connection_info()
    print_info(info)
