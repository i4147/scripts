from __future__ import annotations

import base64
import csv
import hashlib
import site
import sys
from pathlib import Path


def get_site_packages() -> list[Path]:
    paths: set[Path] = set(site.getsitepackages())
    user = site.getusersitepackages()
    if user:
        paths.add(user)
    return [Path(p) for p in paths if Path(p).exists()]


def normalize_dist(name: str) -> str:
    return name.lower().replace("-", "_")


def dist_name_from_dir(d: Path) -> str:
    base = d.name[:-10]
    return normalize_dist(base.split("-", 1)[0])


def parse_record(
    dist_info: Path,
) -> dict[Path, str | None]:
    record = dist_info / "RECORD"
    files: dict[Path, str | None] = {}
    if not record.exists():
        return files
    try:
        with record.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                rel, hashval = row[0], (row[1] if len(row) > 1 else None)
                if rel.endswith(".pyc"):
                    continue
                if ".dist-info/" in rel:
                    continue
                files[(dist_info.parent / rel).resolve()] = hashval
    except Exception as exc:
        print(
            f"[ERROR] RECORD parse failed: {dist_info}: {exc}",
            file=sys.stderr,
        )
    return files


def compute_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return "sha256=" + base64.urlsafe_b64encode(h.digest()).decode().rstrip("=")


def infer_top_levels(dist_info: Path) -> set[str]:
    tops: set[str] = set()
    site_root = dist_info.parent.resolve()
    for p in parse_record(dist_info):
        try:
            p = p.resolve()
        except OSError:
            continue
        try:
            rel = p.relative_to(site_root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) == 1 and p.suffix == ".py":
            tops.add(p.stem)
        elif len(parts) >= 2 and parts[1] == "__init__.py":
            tops.add(parts[0])
    return tops


def main() -> None:
    empty_pkgs: list[Path] = []
    missing_files: dict[str, set[Path]] = {}
    duplicates: dict[str, list[Path]] = {}
    ownership: dict[Path, dict[Path, str | None]] = {}
    for site_dir in get_site_packages():
        dist_map: dict[str, list[Path]] = {}
        for dist_info in site_dir.glob("*.dist-info"):
            name = dist_name_from_dir(dist_info)
            dist_map.setdefault(name, []).append(dist_info)
            files = parse_record(dist_info)
            ownership[dist_info] = files
            tops = infer_top_levels(dist_info)
            if not tops:
                empty_pkgs.append(dist_info)
            else:
                top_file = dist_info / "top_level.txt"
                if not top_file.exists() or top_file.stat().st_size == 0:
                    top_file.write_text("\n".join(sorted(tops)) + "\n")
                    print(f"[FIXED] {dist_info.name} → {', '.join(sorted(tops))}")
            for p in files:
                if not p.exists():
                    missing_files.setdefault(name, set()).add(p)
        duplicates.update({name: infos for name, infos in dist_map.items() if len(infos) > 1})
    print("[DUPLICATE VERSION ANALYSIS]")
    for name, infos in duplicates.items():
        print(f"\n{name}:")
        file_map: dict[Path, list[Path]] = {}
        for dist in infos:
            for f in ownership.get(dist, {}):
                file_map.setdefault(f, []).append(dist)
        conflicted = False
        for f, owners in file_map.items():
            if len(owners) > 1:
                hashes = set()
                for o in owners:
                    recorded = ownership[o].get(f)
                    if recorded and f.exists():
                        try:
                            if compute_hash(f) == recorded:
                                hashes.add(o)
                        except OSError:
                            pass
                if len(hashes) != 1:
                    conflicted = True
        if conflicted:
            print("  ⚠ overlapping files detected — auto-cleanup unsafe")
        else:
            ordered = sorted(infos, key=lambda p: p.name)
            keep = ordered[-1]
            remove = ordered[:-1]
            print(f"  keep   → {keep.name}")
            for r in remove:
                print(f"  remove → {r.name} (safe candidate)")
    if empty_pkgs:
        print("\n[EMPTY DISTRIBUTIONS]")
        for d in empty_pkgs:
            print(f" - {d}")
    if missing_files:
        print("\n[MISSING FILES]")
        for name, files in missing_files.items():
            print(f" - {name} ({len(files)} files missing)")
    print("\nInspection complete.")


if __name__ == "__main__":
    main()
