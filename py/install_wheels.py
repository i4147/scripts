from __future__ import annotations

import platform
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def is_pure_python_wheel(wheel_path: Path) -> bool:
    wheel_name = wheel_path.stem
    if "-none-any" in wheel_name:
        return True
    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith((".dist-info/WHEEL", ".dist-info/METADATA")):
                    with zf.open(name) as f:
                        content = f.read().decode("utf-8")
                        if "Root-Is-Purelib: true" in content:
                            return True
                        if "Root-Is-Purelib: false" in content:
                            return False
    except Exception as e:
        print(f"Warning: Could not inspect {wheel_path.name}: {e}")
    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith((".so", ".pyd", ".dll", ".dylib")):
                    return False
        return True
    except Exception as e:
        print(f"Warning: Could not inspect {wheel_path.name}: {e}")
        return False


def install_wheel(wheel_path: Path, user_install: bool) -> tuple[Path, bool, str]:
    try:
        cmd = [sys.executable, "-m", "pip", "install", str(wheel_path)]
        if user_install:
            cmd.insert(3, "--user")
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        install_type = "user site-packages" if user_install else "system site-packages"
        return wheel_path, True, f"✓ {wheel_path.name} -> {install_type}"
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else str(e)
        return wheel_path, False, f"✗ {wheel_path.name}: {error_msg}"
    except Exception as e:
        return wheel_path, False, f"✗ {wheel_path.name}: {e!s}"


def get_wheel_type(wheel_path: Path) -> str:
    try:
        wheel_name = wheel_path.stem
        parts = wheel_name.split("-")
        if len(parts) >= 4:
            platform_tag = parts[-1]
            if "none-any" in wheel_name:
                return "Pure Python (any platform)"
            elif "android" in platform_tag.lower():
                return f"Android-specific ({platform_tag})"
            elif "linux" in platform_tag.lower():
                return f"Linux-specific ({platform_tag})"
            else:
                return f"Platform-specific ({platform_tag})"
    except:
        pass
    return "Unknown"


def main():
    current_dir = Path.cwd()
    wheel_files = list(current_dir.glob("*.whl"))
    if not wheel_files:
        print("No .whl files found in current directory.")
        return
    print(f"Found {len(wheel_files)} wheel(s) in {current_dir}")
    print(f"Python version: {sys.version}")
    print(f"Platform: {platform.platform()}")
    print("-" * 40)
    install_tasks = []
    for wheel in wheel_files:
        is_pure = is_pure_python_wheel(wheel)
        wheel_type = get_wheel_type(wheel)
        install_type = "USER site-packages" if is_pure else "SYSTEM site-packages"
        print(f"Analyzing: {wheel.name}")
        print(f"  Type: {wheel_type}")
        print(f"  Target: {install_type}")
        install_tasks.append((wheel, is_pure))
    print("\n" + "=" * 40)
    print("Starting parallel installation...")
    print("-" * 40)
    successful = []
    failed = []
    max_workers = min(4, len(wheel_files))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_wheel = {executor.submit(install_wheel, wheel, is_pure): wheel for wheel, is_pure in install_tasks}
        for future in as_completed(future_to_wheel):
            wheel = future_to_wheel[future]
            try:
                wheel_path, success, message = future.result()
                print(message)
                if success:
                    successful.append(wheel_path)
                else:
                    failed.append((wheel_path, message))
            except Exception as e:
                print(f"✗ Error processing {wheel.name}: {e}")
                failed.append((wheel, str(e)))
    print("\n" + "=" * 40)
    print("INSTALLATION SUMMARY")
    print("-" * 40)
    print(f"Total wheels: {len(wheel_files)}")
    print(f"✓ Successfully installed: {len(successful)}")
    print(f"✗ Failed: {len(failed)}")
    if successful:
        print("\nSuccessfully installed:")
        for wheel in successful:
            is_pure = is_pure_python_wheel(wheel)
            location = "user site" if is_pure else "system site"
            print(f"  ✓ {wheel.name} -> {location}")
    if failed:
        print("\nFailed installations:")
        for wheel, error in failed:
            print(f"  ✗ {wheel.name}: {error}")
    print("\nDone!")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\nInstallation interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
