from __future__ import annotations

import importlib
import pkgutil
import site
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
OUTPUT_FILE = "errors.txt"
BLUE = "\033[34m"
RESET = "\033[0m"


def get_site_packages_paths() -> list[Path]:
    return [Path(p) for p in site.getsitepackages()]


def get_third_party_packages(
    paths: Iterable[Path],
) -> set[str]:
    packages: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for module in pkgutil.iter_modules([str(path)]):
            name = module.name
            if name.startswith("_"):
                continue
            packages.add(name)
    return packages


def try_import(package: str) -> str | None:
    try:
        importlib.import_module(package)
        return None
    except Exception:
        return traceback.format_exc()


def main() -> None:
    site_packages = get_site_packages_paths()
    packages = sorted(get_third_party_packages(site_packages))
    errors_found = False
    with Path(OUTPUT_FILE).open("w", encoding="utf-8") as log:
        for pkg in packages:
            print(f"testing {pkg}")
            error = try_import(pkg)
            if error:
                errors_found = True
                print(f"{BLUE}{pkg} has errors{RESET}")
                log.write(f"{'=' * 80}\n")
                log.write(f"PACKAGE: {pkg}\n")
                log.write(error)
                log.write("\n")
    if errors_found:
        print(f"{BLUE}Errors found. See '{OUTPUT_FILE}'.{RESET}")
    else:
        print("No import errors detected.")


if __name__ == "__main__":
    main()
