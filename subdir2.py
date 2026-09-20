import shutil
import subprocess
from pathlib import Path
def safe_mkdir(base):
    if not base.exists():
        base.mkdir()
        return base
    i = 1
    while True:
        candidate = base.with_name(f"{base.name}_{i}")
        if not candidate.exists():
            candidate.mkdir()
            return candidate
        i += 1
def unzip_file(archive, target_dir):
    try:
        result = subprocess.run(
            ["unzip", "-o", archive.name],
            cwd=target_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
def main():
    cwd = Path.cwd()
    for item in cwd.iterdir():
        if not item.is_file():
            continue
        base_dir = cwd / item.stem
        target_dir = safe_mkdir(base_dir)
        moved_file = target_dir / item.name
        shutil.move(str(item), moved_file)
        ok = unzip_file(moved_file, target_dir)
        if ok:
            moved_file.unlink()
            print(f"[OK] Unzipped and removed: {item.name}")
        else:
            print(f"[SKIP] Not a zip or unzip failed: {item.name}")
if __name__ == "__main__":
    raise SystemExit(main())
