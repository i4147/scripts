from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
from collections import defaultdict
from email.parser import Parser
from packaging.utils import canonicalize_name


def read_wheel_metadata(wheel_path: Path):
    with ZipFile(wheel_path) as zf:
        meta_name = next((n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None)
        wheel_name = next((n for n in zf.namelist() if n.endswith(".dist-info/WHEEL")), None)

        if meta_name is None or wheel_name is None:
            raise ValueError("missing METADATA or WHEEL")

        meta = Parser().parsestr(zf.read(meta_name).decode("utf-8", errors="replace"))
        name = meta.get("Name")
        version = meta.get("Version")
        if not name or not version:
            raise ValueError("missing Name or Version in METADATA")

        wheel_text = zf.read(wheel_name).decode("utf-8", errors="replace")
        tags = []
        for line in wheel_text.splitlines():
            if line.startswith("Tag: "):
                tags.append(line[5:].strip())

        if not tags:
            raise ValueError("missing Tag in WHEEL")

        dist = canonicalize_name(name).replace("-", "_")
        return dist, version, tags


def safe_target_path(dest: Path) -> Path:
    if not dest.exists():
        return dest
    i = 1
    while True:
        candidate = dest.with_name(f"{dest.stem}.{i}{dest.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def restore_wheel_names(folder: str | Path) -> None:
    folder = Path(folder)
    conflict_dir = folder / "_wheel_name_conflicts"
    conflict_dir.mkdir(exist_ok=True)

    versions_by_pkg = defaultdict(set)

    for src in sorted(folder.iterdir()):
        if not src.is_file() or src.suffix != ".whl":
            continue

        try:
            dist, version, tags = read_wheel_metadata(src)
            versions_by_pkg[dist].add(version)
        except Exception as e:
            print(f"SKIP  {src.name}  ({e})")
            continue

        tag_part = tags[0]
        dest = folder / f"{dist}-{version}-{tag_part}.whl"

        if dest.exists() and dest.resolve() != src.resolve():
            moved = safe_target_path(conflict_dir / src.name)
            src.rename(moved)
            print(f"CONFLICT {src.name} -> moved to {moved.name}")
        elif dest.resolve() == src.resolve():
            print(f"OK    {src.name} -> already correct")
        else:
            src.rename(dest)
            print(f"RENAMED {src.name} -> {dest.name}")

    for pkg, versions in sorted(versions_by_pkg.items()):
        if len(versions) > 1:
            print(f"MULTIPLE VERSIONS: {pkg} -> {sorted(versions)}")
