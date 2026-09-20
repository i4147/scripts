
import importlib.metadata
import logging
import sys
from pathlib import Path


logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(message)s", handlers=[logging.StreamHandler(sys.stdout)]
)


def check_package_files(dist) -> list[str]:
    missing_files = []

    
    if dist.files is None:
        
        return missing_files

    for package_file in dist.files:
        
        file_path = Path(dist.locate_file(package_file))

        
        if file_path.suffix == ".pyc":
            continue

        if not file_path.exists():
            missing_files.append(str(package_file))

    return missing_files


def check_package_dependencies(dist, installed_map: dict[str, str]) -> list[str]:
    broken_deps = []

    if dist.requires is None:
        return broken_deps

    for req_str in dist.requires:
        
        
        dep_name = req_str.split(";")[0].strip()

        
        for op in ["<", ">", "=", "!", "~"]:
            if op in dep_name:
                dep_name = dep_name.split(op)[0].strip()

        if not dep_name:
            continue

        
        if dep_name.lower() not in installed_map:
            broken_deps.append(req_str)

    return broken_deps


def main():
    logging.info("Starting site-packages verification scan...\n")

    
    distributions = list(importlib.metadata.distributions())

    
    installed_map = {d.metadata["Name"].lower(): d.version for d in distributions}

    corrupted_packages_count = 0
    broken_deps_count = 0

    for dist in distributions:
        pkg_name = dist.metadata["Name"]
        pkg_version = dist.version

        
        origin_path = getattr(dist, "_path", "Unknown Environment Space")

        
        missing_files = check_package_files(dist)

        
        missing_deps = check_package_dependencies(dist, installed_map)

        
        if missing_files or missing_deps:
            print(f"📦 PACKAGE: {pkg_name} ({pkg_version})")
            print(f"   Location Target: {origin_path}")

            if missing_files:
                corrupted_packages_count += 1
                print(f"   ❌ Missing Files ({len(missing_files)}):")
                
                for f in missing_files[:5]:
                    print(f"      - {f}")
                if len(missing_files) > 5:
                    print(f"      - ... and {len(missing_files) - 5} more files missing.")

            if missing_deps:
                broken_deps_count += 1
                print(f"   ⚠️  Unresolved Dependencies:")
                for dep in missing_deps:
                    print(f"      - Missing requirement: {dep}")

            print("-" * 60)

    
    logging.info("=== SCAN SUMMARY ===")
    logging.info(f"Total packages evaluated: {len(distributions)}")
    logging.info(f"Packages with missing files: {corrupted_packages_count}")
    logging.info(f"Packages with missing dependencies: {broken_deps_count}")


if __name__ == "__main__":
    main()
