import platform
import subprocess
import sys
import zipfile
from multiprocessing.pool import ApplyResult, Pool
from pathlib import Path
from typing import Final
from loguru import logger
POOL_SIZE = 8
PURE_PYTHON_MARKER = "-none-any"
ROOT_IS_PURELIB_TRUE = "Root-Is-Purelib: true"
ROOT_IS_PURELIB_FALSE = "Root-Is-Purelib: false"
BINARY_EXTENSIONS = (".so", ".pyd", ".dll", ".dylib")
METADATA_SUFFIXES = (".dist-info/WHEEL", ".dist-info/METADATA")
def is_pure_python_wheel(wheel_path):
    wheel_name = wheel_path.stem
    if PURE_PYTHON_MARKER in wheel_name:
        return True
    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(METADATA_SUFFIXES):
                    with zf.open(name) as f:
                        content = f.read().decode("utf-8")
                        if ROOT_IS_PURELIB_TRUE in content:
                            return True
                        if ROOT_IS_PURELIB_FALSE in content:
                            return False
    except Exception as exc:  
        logger.warning(f"Could not inspect {wheel_path.name}: {exc}")
    try:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith(BINARY_EXTENSIONS):
                    return False
        return True
    except Exception as exc:  
        logger.warning(f"Could not inspect {wheel_path.name}: {exc}")
        return False
def get_wheel_type(wheel_path):
    try:
        wheel_name = wheel_path.stem
        parts = wheel_name.split("-")
        if len(parts) >= 4:
            platform_tag = parts[-1]
            if "none-any" in wheel_name:
                return "Pure Python (any platform)"
            if "android" in platform_tag.lower():
                return f"Android-specific ({platform_tag})"
            if "linux" in platform_tag.lower():
                return f"Linux-specific ({platform_tag})"
            return f"Platform-specific ({platform_tag})"
    except Exception:  
        pass
    return "Unknown"
def install_wheel(wheel_path, user_install):
    try:
        cmd = [sys.executable, "-m", "pip", "install", str(wheel_path)]
        if user_install:
            cmd.insert(3, "--user")
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        install_type = "user site-packages" if user_install else "system site-packages"
        return wheel_path, True, f"✓ {wheel_path.name} -> {install_type}"
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.strip() if exc.stderr else str(exc)
        return wheel_path, False, f"✗ {wheel_path.name}: {error_msg}"
    except Exception as exc:  
        return wheel_path, False, f"✗ {wheel_path.name}: {exc!s}"
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
    print("=" * 40)
    print("Starting parallel installation...")
    print("-" * 40)
    successful = []
    failed = []
    with Pool(processes=POOL_SIZE) as pool:
        async_results = [
            pool.apply_async(install_wheel, (wheel, is_pure))
            for wheel, is_pure in install_tasks
        ]
        for async_result in async_results:
            try:
                wheel_path, success, message = async_result.get()
                print(message)
                if success:
                    successful.append(wheel_path)
                else:
                    failed.append((wheel_path, message))
            except Exception as exc:  
                logger.error(f"✗ Error processing wheel: {exc}")
                failed.append((Path("<unknown>"), str(exc)))
    print("=" * 40)
    print("INSTALLATION SUMMARY")
    print("-" * 40)
    print(f"Total wheels: {len(wheel_files)}")
    print(f"✓ Successfully installed: {len(successful)}")
    print(f"✗ Failed: {len(failed)}")
    if successful:
        print("Successfully installed:")
        for wheel in successful:
            is_pure = is_pure_python_wheel(wheel)
            location = "user site" if is_pure else "system site"
            print(f"  ✓ {wheel.name} -> {location}")
    if failed:
        print("Failed installations:")
        for wheel, error in failed:
            print(f"  ✗ {wheel.name}: {error}")
    print("Done!")
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("Installation interrupted by user.")
        sys.exit(1)
    except Exception as exc:  
        logger.error(f"Error: {exc}")
        sys.exit(1)
