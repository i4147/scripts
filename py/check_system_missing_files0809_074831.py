import os
import sys
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import subprocess


def get_prefix():
    return os.environ.get("PREFIX", "/data/data/com.termux/files/usr")


def should_ignore(file_path):
    exclude = {"share/man", "share/info", "share/doc", "share/LICENSES"}
    return any(excl in file_path for excl in exclude)


def is_file_path(path):
    p = Path(path)
    if p.exists():
        return p.is_file()
    return "." in p.name


def check_package_files(package_name, prefix):
    try:
        result = subprocess.run(["dpkg", "-L", package_name], capture_output=True, text=True, timeout=5)

        if result.returncode != 0:
            return package_name, None

        missing = []
        for file_path in result.stdout.strip().split("\n"):
            if not file_path or should_ignore(file_path) or not is_file_path(file_path):
                continue

            full_path = Path(prefix) / file_path.lstrip("/")
            if not full_path.exists():
                missing.append(file_path)

        return package_name, missing if missing else None
    except Exception:
        return package_name, None


def main():
    prefix = get_prefix()
    output_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("missing_files.json")

    print(f"PREFIX: {prefix}")
    result = subprocess.run(["dpkg", "-l"], capture_output=True, text=True)
    packages = [line.split()[1] for line in result.stdout.split("\n") if line.startswith("ii")]

    print(f"Scanning {len(packages)} packages...")
    results = {}

    with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        futures = {executor.submit(check_package_files, pkg, prefix): pkg for pkg in packages}
        for i, future in enumerate(as_completed(futures), 1):
            pkg, missing = future.result()
            if missing:
                results[pkg] = missing
            if i % 10 == 0:
                print(f"  {i}/{len(packages)}")

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ {len(results)} packages with missing files → {output_file}")
    print(f"  Total missing: {sum(len(f) for f in results.values())}")


if __name__ == "__main__":
    main()
