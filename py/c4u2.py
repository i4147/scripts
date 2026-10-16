import asyncio
import json
import operator
import re
import sys
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup

MIRROR_BASE = "https://mirror-pypi.runflare.com"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


def extract_version(filename: str) -> str:
    match = re.match("^[a-zA-Z0-9_.-]+-([0-9][a-zA-Z0-9._-]*)", filename)
    return match.group(1) if match else "unknown"


async def fetch_pkg(session: aiohttp.ClientSession, pkg_name: str):
    url = f"{MIRROR_BASE}/{pkg_name}"
    html_path = OUTPUT_DIR / f"{pkg_name}.html"
    try:
        async with session.get(url, timeout=15) as resp:
            if resp.status != 200:
                return {"pkg_name": pkg_name, "error": f"HTTP {resp.status}"}
            html = await resp.text()
            html_path.write_text(html, encoding="utf-8")
            soup = BeautifulSoup(html, "html.parser")
            links = soup.find_all("a", href=True)
            if not links:
                return {"pkg_name": pkg_name, "error": "No links found"}
            candidates = []
            for a in links:
                href = a["href"]
                filename = href.split("/")[-1].split("#")[0]
                if any((ext in filename for ext in [".tar.gz", ".whl", ".zip"])):
                    candidates.append((href, filename))
            if not candidates:
                return {"pkg_name": pkg_name, "error": "No downloadable files"}
            tar_gz = [(h, f) for h, f in candidates if ".tar.gz" in f]
            others = [(h, f) for h, f in candidates if ".tar.gz" not in f]
            if tar_gz:
                href, filename = tar_gz[-1]
            else:
                href, filename = others[-1]
                version = extract_version(filename)
            return {"pkg_name": pkg_name, "latest_version": version, "url_of_latest_version": href}
    except Exception as e:
        return {"pkg_name": pkg_name, "error": str(e)}


async def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_latest.py <packages_file>")
        sys.exit(1)
    pkg_file = sys.argv[1]
    if not Path(pkg_file).is_file():
        print(f"Error: File '{pkg_file}' not found.")
        sys.exit(1)
    with Path(pkg_file).open("r", encoding="utf-8") as f:
        packages = [line.strip() for line in f if line.strip() and (not line.startswith("#"))]
    if not packages:
        print("No packages found in input file.")
        return
    print(f"Processing {len(packages)} packages concurrently...")
    results = []
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_pkg(session, pkg) for pkg in packages]
        for task in asyncio.as_completed(tasks):
            res = await task
            results.append(res)
            pkg = res.get("pkg_name", "?")
            if "error" in res:
                print(f"❌ {pkg}: {res['error']}")
            else:
                print(f"✅ {pkg}: {res['latest_version']} — {res['url_of_latest_version']}")
    results.sort(key=operator.itemgetter("pkg_name"))
    with Path("results.json").open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\n✅ Done. Results saved to `results.json`. HTML saved to `./output/`.")


if __name__ == "__main__":
    asyncio.run(main())
