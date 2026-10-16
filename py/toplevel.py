from __future__ import annotations

import csv
import site
import sys
from pathlib import Path


def get_site_packages() -> list[Path]:
    paths: set[Path] = set()
    paths.update(Path(p) for p in site.getsitepackages())
    user_site = site.getusersitepackages()
    if user_site:
        paths.add(Path(user_site))
    return sorted(p for p in paths if p.exists())


def infer_top_levels(dist_info: Path) -> set[str]:
    record = dist_info / "RECORD"
    if not record.exists():
        return set()
    top_levels: set[str] = set()
    try:
        with record.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                rel = row[0]
                if rel.startswith((".", "/", "\\")):
                    continue
                if rel.endswith(".dist-info") or ".dist-info/" in rel:
                    continue
                if ".data/" in rel:
                    continue
                parts = rel.split("/")
                if len(parts) == 1:
                    top_levels.add(Path(rel).stem)
                else:
                    top_levels.add(parts[0])
    except Exception as exc:
        print(
            f"[ERROR] Failed to parse RECORD: {record} ({exc})",
            file=sys.stderr,
        )
    return top_levels


def fix_dist_info(dist_info: Path) -> bool:
    top_level = dist_info / "top_level.txt"
    if top_level.exists() and top_level.stat().st_size > 0:
        return False
    inferred = infer_top_levels(dist_info)
    if not inferred:
        print(f"[WARN ] Could not infer top-level modules for {dist_info.name}")
        return False
    top_level.write_text(
        "\n".join(sorted(inferred)) + "\n",
        encoding="utf-8",
    )
    print(f"[FIXED] {dist_info.name} → {', '.join(sorted(inferred))}")
    return True


def main() -> None:
    fixed = 0
    scanned = 0
    for site_dir in get_site_packages():
        for dist_info in site_dir.glob("*.dist-info"):
            scanned += 1
            if fix_dist_info(dist_info):
                fixed += 1
    print()
    print(f"Scanned dist-info dirs : {scanned}")
    print(f"Repaired top_level.txt: {fixed}")


if __name__ == "__main__":
    main()
