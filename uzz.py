from multiprocessing import Pool
from pathlib import Path
from zipfile import ZipFile
from loguru import logger
MAX_WORKERS = 8
def get_package_name(wheel_filename):
    parts = wheel_filename.replace(".whl", "").split("-")
    for i, part in enumerate(parts):
        if part and part[0].isdigit():
            return "-".join(parts[:i])
    return parts[0]
def extract_wheel(wheel_path):
    pkg_name = get_package_name(wheel_path.name)
    output_dir = wheel_path.parent / pkg_name
    output_dir.mkdir(exist_ok=True)
    try:
        with ZipFile(wheel_path) as whl:
            whl.extractall(output_dir)
        wheel_path.unlink()
        return wheel_path.name, True
    except Exception as e:
        return f"{wheel_path.name}: {e}", False
def main():
    wheels = list(Path.cwd().glob("*.whl"))
    if not wheels:
        print("No .whl files found")
        return 0
    results = []
    with Pool(processes=MAX_WORKERS) as pool:
        async_results = [pool.apply_async(extract_wheel, (w,)) for w in wheels]
        for ar in async_results:
            try:
                results.append(ar.get())
            except Exception as e:  
                results.append(e)
    for result in results:
        if isinstance(result, BaseException):
            logger.error(f"✗ {result}")
            continue
        name, success = result
        status = "✓" if success else "✗"
        if success:
            print(f"{status} {name}")
        else:
            logger.error(f"{status} {name}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
