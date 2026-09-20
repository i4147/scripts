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
CYAN = "\033[96m"
RESET = "\033[0m"


PKG_MAP = {
    "absl": "absl_py",
    "dotenv": "python_dotenv",
    "cv2": "opencv_python",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "sklearn": "scikit_learn",
    "scipy": "scipy",
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "tensorflow": "tensorflow",
    "torch": "torch",
    "keras": "keras",
    "flask": "flask",
    "django": "django",
    "requests": "requests",
    "bs4": "beautifulsoup4",
    "beautifulsoup4": "bs4",
    "dateutil": "python_dateutil",
    "cryptography": "cryptography",
    "Pygments": "pygments",
    "yaml": "pyyaml",
    "Cython": "cython",
    "cffi": "cffi",
    "markdown": "markdown",
    "jinja2": "jinja2",
    "click": "click",
    "werkzeug": "werkzeug",
    "itsdangerous": "itsdangerous",
    
}


def get_package_name(import_name):
    
    if import_name in PKG_MAP:
        return PKG_MAP[import_name]

    
    variants = [
        import_name,
        import_name.replace("_", "-"),
        import_name.replace("-", "_"),
        import_name.lower(),
        import_name.upper(),
        import_name.title(),
    ]

    
    for variant in set(variants):
        if (PREFIX_SITE_PACKAGES / variant).exists():
            return variant

        
        dist_info_pattern = f"{variant}-*.dist-info"
        if any(PREFIX_SITE_PACKAGES.glob(dist_info_pattern)):
            return variant

    return import_name


def move_package(import_name):
    pkg_name = get_package_name(import_name)
    src = PREFIX_SITE_PACKAGES / pkg_name
    dest = USER_SITE_PACKAGES / pkg_name

    
    if not src.exists():
        
        dist_info_pattern = f"{pkg_name}-*.dist-info"
        if any(PREFIX_SITE_PACKAGES.glob(dist_info_pattern)):
            return ("dist_info_only", import_name, pkg_name, None)
        return ("not_found", import_name, pkg_name, None)

    
    if dest.exists():
        return ("exists", import_name, pkg_name, None)

    try:
        
        shutil.move(str(src), str(dest))

        
        moved_info = []
        dist_info_pattern = f"{pkg_name}-*.dist-info"
        for info_dir in PREFIX_SITE_PACKAGES.glob(dist_info_pattern):
            dest_info = USER_SITE_PACKAGES / info_dir.name
            if not dest_info.exists():
                shutil.move(str(info_dir), str(dest_info))
                moved_info.append(info_dir.name)

        return ("success", import_name, pkg_name, moved_info)

    except Exception as e:
        return ("error", import_name, pkg_name, str(e))


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
    print(f"{YELLOW}Termux Python Package Mover (Parallel with List Update){RESET}")
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

    
    successful = []
    exists = []
    not_found = []
    errors = []
    mismatches = []
    dist_info_only = []

    print()
    for status, import_name, pkg_name, extra in results:
        if status == "success":
            print(f"{GREEN}✅ {import_name} -> {pkg_name}: Moved successfully{RESET}")
            if extra:
                print(f"   📁 Moved dist-info: {', '.join(extra)}")
            successful.append(import_name)

        elif status == "exists":
            print(f"{YELLOW}⏭️  {import_name} -> {pkg_name}: Already exists in destination{RESET}")
            exists.append(import_name)

        elif status == "dist_info_only":
            print(f"{CYAN}📦 {import_name} -> {pkg_name}: Only dist-info found (package may already be moved){RESET}")
            dist_info_only.append(import_name)
            

        elif status == "not_found":
            if import_name != pkg_name:
                print(f"{CYAN}🔍 {import_name}: Package might be named '{pkg_name}' (mapped){RESET}")
                mismatches.append((import_name, pkg_name))
            else:
                print(f"{RED}⚠️  {import_name}: Not found in source{RESET}")
                not_found.append(import_name)

        elif status == "error":
            print(f"{RED}❌ {import_name} -> {pkg_name}: Failed - {extra}{RESET}")
            errors.append(import_name)

    
    
    keep_packages = []
    for pkg in packages:
        
        if pkg not in successful and pkg not in dist_info_only:
            
            mismatch_found = any(m[0] == pkg for m in mismatches)
            if mismatch_found:
                print(f"{YELLOW}📝 Keeping {pkg} in list (name mismatch - manual attention needed){RESET}")
                keep_packages.append(pkg)
            else:
                keep_packages.append(pkg)

    
    if keep_packages:
        with open(PKG_LIST, "w") as f:
            f.write("\n".join(keep_packages))
            if keep_packages:
                f.write("\n")
        print(f"{YELLOW}Updated package list saved to: {PKG_LIST}{RESET}")
    else:
        
        if PKG_LIST.exists():
            PKG_LIST.unlink()
    
    print()
    print(f"{YELLOW}Summary:{RESET}")
    print(f"  Total packages: {total_pkgs}")
    print(f"  Successfully moved: {GREEN}{len(successful)}{RESET}")
    print(f"  Already existed (skipped): {YELLOW}{len(exists)}{RESET}")
    print(f"  Dist-info only (likely already moved): {CYAN}{len(dist_info_only)}{RESET}")
    print(f"  Not found: {RED}{len(not_found)}{RESET}")
    print(f"  Errors: {RED}{len(errors)}{RESET}")
    print(f"  Name mismatches (kept in list): {CYAN}{len(mismatches)}{RESET}")
    print(f"  Remaining in list: {len(keep_packages)}")
    print(f"  Time taken: {duration:.2f}s")

    if mismatches:
        print()
        print(f"{CYAN}Name mismatches detected (manual attention needed):{RESET}")
        for imp, pkg in mismatches:
            print(f"  {imp} -> {pkg}")
        print()
        print(f"{YELLOW}You can add these mappings to the PKG_MAP dictionary in the script{RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
