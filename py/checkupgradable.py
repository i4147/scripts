
import functools
import json
import os
import subprocess
import sys
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Dict, Set, Tuple

import pkg_resources


OUTPUT_FILE = "/sdcard/s4u.json"
UPGRADABLE_FILE = "/sdcard/upgradable.json"
CHECKPOINT_FILE = "/sdcard/checkpoint.json"
MAX_WORKERS = max(1, cpu_count() - 1)  


def get_installed_packages() -> Dict[str, str]:
    packages = {}
    try:
        
        for dist in pkg_resources.working_set:
            
            if "site-packages" in str(dist.location):
                packages[dist.project_name] = dist.version
    except Exception as e:
        print(f"Error getting installed packages: {e}")
        sys.exit(1)
    return packages


def get_latest_version(package_name: str, current_version: str) -> Tuple[str, str, bool]:
    try:
        
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", package_name], capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            
            for line in result.stdout.split("\n"):
                if "Available versions:" in line or "LATEST:" in line:
                    
                    parts = line.split()
                    for part in parts:
                        if part[0].isdigit() or part[0] == "v":
                            latest = part.strip(",)")
                            
                            is_upgradable = compare_versions(latest, current_version)
                            return (package_name, latest, is_upgradable)
    except subprocess.TimeoutExpired:
        print(f"Timeout checking {package_name}")
    except Exception as e:
        print(f"Error checking {package_name}: {e}")

    return (package_name, current_version, False)


def compare_versions(latest: str, current: str) -> bool:
    
    try:
        
        latest = latest.lstrip("vV")
        current = current.lstrip("vV")

        
        latest_parts = [int(x) for x in latest.split(".") if x.isdigit()]
        current_parts = [int(x) for x in current.split(".") if x.isdigit()]

        
        for l, c in zip(latest_parts, current_parts):
            if l > c:
                return True
            elif l < c:
                return False

        
        return len(latest_parts) > len(current_parts)
    except:
        
        return latest != current


def load_checkpoint() -> Tuple[Set[str], Dict[str, Dict[str, str]]]:
    processed_packages = set()
    results = {}

    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                checkpoint = json.load(f)
                processed_packages = set(checkpoint.get("processed", []))
                results = checkpoint.get("results", {})
            print(f"Resuming from checkpoint: {len(processed_packages)} packages already processed")
        except Exception as e:
            print(f"Error loading checkpoint: {e}")

    return processed_packages, results


def save_checkpoint(processed: Set[str], results: Dict) -> None:
    checkpoint = {"processed": list(processed), "results": results, "total_processed": len(processed)}
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(checkpoint, f, indent=2)
    except Exception as e:
        print(f"Error saving checkpoint: {e}")


def process_packages_parallel(packages: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    results = {}
    processed_packages, saved_results = load_checkpoint()
    results.update(saved_results)

    
    pending_packages = {name: version for name, version in packages.items() if name not in processed_packages}

    if not pending_packages:
        print("All packages already processed!")
        return results

    print(f"Processing {len(pending_packages)} packages using {MAX_WORKERS} workers...")

    
    check_func = functools.partial(check_package_version, packages=packages)

    
    package_items = list(pending_packages.items())
    chunk_size = max(1, len(package_items) // 100)  

    with Pool(processes=MAX_WORKERS) as pool:
        for i, (package_name, version, latest, is_upgradable) in enumerate(
            pool.imap_unordered(check_func, package_items), 1
        ):
            results[package_name] = {"installed_version": version, "latest_version": latest}
            processed_packages.add(package_name)

            
            if i % 10 == 0:  
                save_checkpoint(processed_packages, results)
                print(f"Progress: {i}/{len(pending_packages)} packages checked")

            
            if i % chunk_size == 0 or i == len(pending_packages):
                percent = (i / len(pending_packages)) * 100
                print(f"Progress: {percent:.1f}% ({i}/{len(pending_packages)})")

    
    save_checkpoint(processed_packages, results)

    return results


def check_package_version(package_info: Tuple[str, str], packages: Dict) -> Tuple[str, str, str, bool]:
    package_name, current_version = package_info
    package_name, latest_version, is_upgradable = get_latest_version(package_name, current_version)
    return (package_name, current_version, latest_version, is_upgradable)


def save_results(results: Dict) -> None:
    
    try:
        
        Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)

        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2)
        print(f"All results saved to {OUTPUT_FILE}")
    except Exception as e:
        print(f"Error saving results: {e}")

    
    upgradable = {name: info for name, info in results.items() if info["installed_version"] != info["latest_version"]}

    try:
        with open(UPGRADABLE_FILE, "w") as f:
            json.dump(upgradable, f, indent=2)
        print(f"Upgradable packages ({len(upgradable)}) saved to {UPGRADABLE_FILE}")
    except Exception as e:
        print(f"Error saving upgradable packages: {e}")


def main() -> None:
    print("Starting package update checker...")
    print(f"Output directory: /sdcard/")

    
    print("Scanning installed packages in system site-packages...")
    installed_packages = get_installed_packages()
    print(f"Found {len(installed_packages)} installed packages")

    if not installed_packages:
        print("No packages found in system site-packages!")
        return

    
    results = process_packages_parallel(installed_packages)

    
    save_results(results)

    
    upgradable_count = sum(1 for info in results.values() if info["installed_version"] != info["latest_version"])

    print(f"\nSummary:")
    print(f"Total packages checked: {len(results)}")
    print(f"Upgradable packages: {upgradable_count}")
    print(f"Up-to-date packages: {len(results) - upgradable_count}")

    
    if len(results) == len(installed_packages):
        try:
            os.remove(CHECKPOINT_FILE)
            print("Checkpoint file cleaned up")
        except:
            pass


if __name__ == "__main__":
    main()
