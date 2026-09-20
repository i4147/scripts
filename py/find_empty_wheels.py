from pathlib import Path
from zipfile import ZipFile


def is_wheel_only_dist_info(path: Path) -> bool:
    print(f"processing {path}")
    try:
        with ZipFile(path, "r") as zf:
            namelist = zf.namelist()
            dist_info_dirs = [f for f in namelist if f.endswith(".dist-info/")]
            if not dist_info_dirs:
                return False
            dist_info_dir = dist_info_dirs[0]
            return all(name.startswith(dist_info_dir) or name == "" for name in namelist)
    except Exception:
        return False


def main() -> None:
    cwd = Path("/sdcard/whl")
    wheels = [f for f in cwd.rglob("*.whl")]
    if not wheels:
        print("No .whl files found in current directory.")
        return
    print("Checking wheel files...\n")
    only_dist_info = [wheel for wheel in wheels if is_wheel_only_dist_info(wheel)]
    if only_dist_info:
        print("Wheels that contain ONLY dist-info/ directory:")
        for w in only_dist_info:
            print(f"  {w}")
    else:
        print("No wheels found that contain only dist-info/ directory.")


if __name__ == "__main__":
    main()
