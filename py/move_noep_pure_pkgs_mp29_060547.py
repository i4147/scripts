import shutil
import sys
from pathlib import Path
from multiprocessing import Pool, cpu_count
from datetime import datetime


PREFIX = "/data/data/com.termux/files/usr"
PYTHON_VERSION = "3.13"
PREFIX_SITE_PACKAGES = Path(PREFIX) / f"lib/python{PYTHON_VERSION}/site-packages"
USER_SITE_PACKAGES = Path.home() / f".local/lib/python{PYTHON_VERSION}/site-packages"
PKG_LIST = PREFIX_SITE_PACKAGES / "noep-pure.txt"


GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"


def move_package(pkg_name):
    src = PREFIX_SITE_PACKAGES / pkg_name
    dest = USER_SITE_PACKAGES / pkg_name

    
    if not src.exists():
        return (pkg_name, "not_found", None)

    
    if dest.exists():
        return (pkg_name, "exists", None)

    try:
        
        shutil.move(str(src), str(dest))

        
        dist_info_pattern = f"{pkg_name}-*.dist-info"
        moved_info = []
        for info_dir in PREFIX_SITE_PACKAGES.glob(dist_info_pattern):
            dest_info = USER_SITE_PACKAGES / info_dir.name
            if not dest_info.exists():
                shutil.move(str(info_dir), str(dest_info))
                moved_info.append(info_dir.name)

        return (pkg_name, "success", moved_info)

    except Exception as e:
        return (pkg_name, "error", str(e))


def main():
    
    if not PKG_LIST.exists():
        print(f"{RED}Error: Package list not found at {PKG_LIST}{RESET}")
        return 1

    
    USER_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)

    
    try:
        with open(PKG_LIST) as f:
            packages = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"{RED}Error reading package list: {e}{RESET}")
        return 1

    total_pkgs = len(packages)
    print(f"{YELLOW}Termux Python Package Mover (Parallel){RESET}")
    print(f"Source: {PREFIX_SITE_PACKAGES}")
    print(f"Destination: {USER_SITE_PACKAGES}")
    print(f"Package list: {PKG_LIST}")
    print(f"{BLUE}Total packages to process: {total_pkgs}{RESET}")
    print()

    
    cpu_count_available = cpu_count()
    num_processes = max(1, (cpu_count_available * 3) // 4)
    print(f"{BLUE}Using {num_processes} parallel processes{RESET}")
    print()

    
    start_time = datetime.now()

    with Pool(processes=num_processes) as pool:
        results = pool.map(move_package, packages)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    
    success = 0
    exists = 0
    not_found = 0
    errors = 0

    print()
    for pkg_name, status, extra in results:
        if status == "success":
            print(f"{GREEN}✅ {pkg_name}: Moved successfully{RESET}")
            if extra:
                print(f"   📁 Moved dist-info: {', '.join(extra)}")
            success += 1
        elif status == "exists":
            print(f"{YELLOW}⏭️  {pkg_name}: Already exists in destination{RESET}")
            exists += 1
        elif status == "not_found":
            print(f"{RED}⚠️  {pkg_name}: Source not found{RESET}")
            not_found += 1
        elif status == "error":
            print(f"{RED}❌ {pkg_name}: Failed - {extra}{RESET}")
            errors += 1

    
    print()
    print(f"{YELLOW}Summary:{RESET}")
    print(f"  Total packages: {total_pkgs}")
    print(f"  Successfully moved: {GREEN}{success}{RESET}")
    print(f"  Already exists: {YELLOW}{exists}{RESET}")
    print(f"  Not found: {RED}{not_found}{RESET}")
    print(f"  Errors: {RED}{errors}{RESET}")
    print(f"  Time taken: {duration:.2f}s")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
