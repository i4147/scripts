import json
from importlib.metadata import distributions
from pathlib import Path

import requests
from dh import cprint
from loguru import logger

logger.remove()
logger.add("/sdcard/updatable.log")


def get_latest_version(pkg_name: str):
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json()["info"]["version"]
        return None
    except Exception:
        return None


def main() -> None:
    results = []
    upgradable = []
    installed_packages = {dist.metadata["Name"]: dist.version for dist in distributions()}
    for pkg, installed_version in installed_packages.items():
        latest_version = get_latest_version(pkg)
        print(f"{pkg}: {installed_version} {latest_version}")
        entry = {"pkgname": pkg, "installed_version": installed_version, "latest_version": latest_version}
        results.append(entry)
        if latest_version and latest_version != installed_version:
            upgradable.append(f"{pkg}=={latest_version}")
            cprint(f"{pkg}=={installed_version} | {latest_version}")
    with Path("/sdcard/updatable.json").open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    Path("/sdcard/requirements.txt").write_text("\n".join(upgradable), encoding="utf-8")
    print("Done.")
    print(f"Checked {len(installed_packages)} installed packages.")
    print(f"Upgradeable packages: {len(upgradable)}")


if __name__ == "__main__":
    main()
