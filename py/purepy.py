from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


def has_native_wheels(info) -> bool:
    urls = info.get("urls", [])
    for u in urls:
        filename = u.get("filename", "").lower()
        if any(ext in filename for ext in [".so", ".pyd", ".dll", "win_amd64", "manylinux", "macosx"]):
            return True
    return False


def check_package(name) -> tuple:
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return name, "not_found"
        info = resp.json()
        if has_native_wheels(info):
            return name, "native"
        return name, "pure"
    except Exception:
        return name, "not_found"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python detect_pure_python.py <package_list.txt>")
        sys.exit(1)
    infile = sys.argv[1]
    pure = set()
    native = set()
    missing = set()
    with Path(infile).open(encoding="utf-8") as f:
        packages = [line.strip() for line in f if line.strip()]
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_package, pkg): pkg for pkg in packages}
        for future in as_completed(futures):
            pkg, result = future.result()
            if result == "pure":
                pure.add(pkg)
            elif result == "native":
                native.add(pkg)
            else:
                missing.add(pkg)
    Path("pure_python.txt").write_text("\n".join(sorted(pure)), encoding="utf-8")
    Path("native_extensions.txt").write_text("\n".join(sorted(native)), encoding="utf-8")
    Path("not_found.txt").write_text("\n".join(sorted(missing)), encoding="utf-8")
    print("Done!")
    print(f"Pure Python: {len(pure)}")
    print(f"Native-required: {len(native)}")
    print(f"Not found: {len(missing)}")


if __name__ == "__main__":
    raise SystemExit(main())
