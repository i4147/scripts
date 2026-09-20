
import os
import zipfile
from pathlib import Path


def find_dist_info_dir(pkg_dir: Path) -> Path | None:
    candidates = [p for p in pkg_dir.iterdir() if p.is_dir() and p.name.endswith(".dist-info")]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise RuntimeError(f"Multiple .dist-info dirs in {pkg_dir}: {candidates}")
    return candidates[0]


def wheel_name_from_dist_info(dist_info_dir: Path) -> str:
    base = dist_info_dir.name
    assert base.endswith(".dist-info")
    base = base[: -len(".dist-info")]
    return f"{base}.whl"


def create_wheel_for_dir(pkg_dir: Path, dest_dir: Path) -> None:
    dist_info = find_dist_info_dir(pkg_dir)
    if dist_info is None:
        print(f"Skipping {pkg_dir}: no *.dist-info dir found.")
        return
    wheel_name = wheel_name_from_dist_info(dist_info)
    wheel_path = dest_dir / wheel_name
    print(f"Packing {pkg_dir} -> {wheel_path}")
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(pkg_dir):
            root_path = Path(root)
            for fname in files:
                file_path = root_path / fname
                arcname = file_path.relative_to(pkg_dir).as_posix()
                zf.write(file_path, arcname)


def main() -> None:
    current = Path.cwd()
    for entry in current.iterdir():
        if entry.is_dir() and (not entry.name.endswith(".dist-info")):
            try:
                create_wheel_for_dir(entry, dest_dir=current)
            except Exception as e:
                print(f"Error while packing {entry}: {e}")
    print("Done.")


if __name__ == "__main__":
    main()
