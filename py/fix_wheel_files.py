import zipfile
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import Optional


def fix_wheel_file(wheel_path: Path) -> tuple[Path, bool, Optional[str]]:
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with zipfile.ZipFile(wheel_path, "r") as whl:
                whl.extractall(temp_path)
            dist_info_dirs = list(temp_path.glob("*.dist-info"))
            if not dist_info_dirs:
                return (wheel_path, False, "No dist-info folder found")
            dist_info = dist_info_dirs[0]
            package_name = dist_info.name.split("-")[0]
            if (temp_path / package_name).exists() and (temp_path / package_name).is_dir():
                return (wheel_path, True, "Already properly structured")
            items_to_move = []
            for item in temp_path.iterdir():
                if item.name != dist_info.name:
                    items_to_move.append(item)
            if not items_to_move:
                return (wheel_path, False, "No files to organize")
            package_folder = temp_path / package_name
            package_folder.mkdir(exist_ok=True)
            for item in items_to_move:
                dest = package_folder / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                item.rename(dest)
            
            
            with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as whl:
                for file_path in temp_path.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(temp_path)
                        whl.write(file_path, arcname)
            return (wheel_path, True, f"Fixed: organized files into '{package_name}/' folder")
    except Exception as e:
        return (wheel_path, False, f"Error: {str(e)}")


def main():
    current_dir = Path.cwd()
    wheel_files = list(current_dir.glob("*.whl"))
    if not wheel_files:
        print("No .whl files found in current directory")
        return
    print(f"Found {len(wheel_files)} .whl file(s) to process")
    print("=" * 60)
    with ProcessPoolExecutor() as executor:
        results = executor.map(fix_wheel_file, wheel_files)
    success_count = 0
    for wheel_path, success, message in results:
        status = "✓ SUCCESS" if success else "✗ FAILED"
        print(f"{status}: {wheel_path.name}")
        print(f"  → {message}")
        if success:
            success_count += 1
    print("=" * 60)
    print(f"Processed: {success_count}/{len(wheel_files)} wheels successfully")
    print("\nOriginal wheels backed up with .bak extension")


if __name__ == "__main__":
    main()
