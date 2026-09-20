
import sys
import json
from pathlib import Path
from multiprocessing import Pool, cpu_count
from typing import List, Tuple, Dict
import argparse
from datetime import datetime
import importlib.util


def get_site_packages_dirs() -> List[Path]:
    site_dirs = []

    
    import site

    for path in site.getsitepackages():
        site_dirs.append(Path(path))

    
    user_site = site.getusersitepackages()
    if user_site:
        site_dirs.append(Path(user_site))

    
    common_paths = [
        Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages",
        Path(sys.prefix)
        / "local"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
    ]

    for path in common_paths:
        if path.exists() and path not in site_dirs:
            site_dirs.append(path)

    
    return [d for d in site_dirs if d.exists() and d.is_dir()]


def is_pure_python_package(package_path: Path) -> bool:
    try:
        
        binary_extensions = {".so", ".pyd", ".dll", ".dylib"}

        
        for item in package_path.rglob("*"):
            if item.is_file():
                
                if item.suffix.lower() in binary_extensions:
                    return False

                
                if item.suffix == ".pyc" and item.stem.endswith("_c"):
                    
                    return False

            
            if item.is_file() and item.suffix == ".pth":
                
                pass

        
        parent = package_path.parent
        for dist_info in parent.glob(f"{package_path.name}*.dist-info"):
            
            record_file = dist_info / "RECORD"
            if record_file.exists():
                content = record_file.read_text(encoding="utf-8", errors="ignore")
                if any(ext in content for ext in binary_extensions):
                    return False

            
            installer_file = dist_info / "INSTALLER"
            if installer_file.exists():
                
                pass

        
        for egg_info in parent.glob(f"{package_path.name}*.egg-info"):
            
            native_file = egg_info / "native_libs.txt"
            if native_file.exists():
                return False

        
        return True

    except Exception as e:
        
        return True


def get_package_name(package_path: Path) -> str:
    
    name = package_path.name
    
    if name.endswith(".dist-info"):
        name = name[:-10]
    elif name.endswith(".egg-info"):
        name = name[:-9]
    
    import re

    name = re.sub(r"-\d+\.\d+\.\d+.*$", "", name)
    return name


def scan_package(package_path: Path) -> Dict[str, any]:
    result = {
        "path": str(package_path),
        "name": get_package_name(package_path),
        "has_entry_points": False,
        "is_pure_python": True,
        "error": None,
    }

    try:
        
        has_entry_points = False

        
        parent = package_path.parent
        pkg_name = get_package_name(package_path)

        dist_info_paths = list(parent.glob(f"{pkg_name}*.dist-info"))
        for dist_info in dist_info_paths:
            entry_points = dist_info / "entry_points.txt"
            if entry_points.exists():
                has_entry_points = True
                break

        
        if not has_entry_points:
            egg_info_paths = list(parent.glob(f"{pkg_name}*.egg-info"))
            for egg_info in egg_info_paths:
                entry_points = egg_info / "entry_points.txt"
                if entry_points.exists():
                    has_entry_points = True
                    break

        
        if not has_entry_points:
            entry_points = package_path / "entry_points.txt"
            if entry_points.exists():
                has_entry_points = True

        result["has_entry_points"] = has_entry_points

        
        if not has_entry_points:
            result["is_pure_python"] = is_pure_python_package(package_path)

    except Exception as e:
        result["error"] = str(e)

    return result


def find_packages_without_entry_points(site_dir: Path) -> Tuple[List[str], List[str]]:
    pure_packages = []
    non_pure_packages = []

    try:
        
        for item in site_dir.iterdir():
            if item.is_dir():
                
                if item.name.startswith("_") or item.name.startswith("."):
                    continue

                
                init_file = item / "__init__.py"
                is_package = init_file.exists() or item.suffix in [".dist-info", ".egg-info"]

                if is_package or item.suffix in [".dist-info", ".egg-info"]:
                    result = scan_package(item)

                    if not result["has_entry_points"] and result["error"] is None:
                        if result["is_pure_python"]:
                            pure_packages.append(result["path"])
                        else:
                            non_pure_packages.append(result["path"])
                    elif result["error"]:
                        print(f"Error scanning {item}: {result['error']}", file=sys.stderr)

    except Exception as e:
        print(f"Error scanning directory {site_dir}: {e}", file=sys.stderr)

    return pure_packages, non_pure_packages


def main():
    parser = argparse.ArgumentParser(
        description="Find Python packages without entry_points.txt in system site directories"
    )
    parser.add_argument(
        "--pure-output", default="noep_pure.txt", help="Output file for pure Python packages (default: noep_pure.txt)"
    )
    parser.add_argument(
        "--nonpure-output",
        default="noep_nopure.txt",
        help="Output file for non-pure packages (default: noep_nopure.txt)",
    )
    parser.add_argument(
        "-j", "--json", action="store_true", help="Output in JSON format (requires output file specification)"
    )
    parser.add_argument(
        "-p", "--processes", type=int, default=None, help=f"Number of processes to use (default: {cpu_count()})"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print verbose output")
    parser.add_argument("-o", "--output", help="Single output file for combined results (overrides separate outputs)")

    args = parser.parse_args()

    
    site_dirs = get_site_packages_dirs()

    if not site_dirs:
        print("No site-packages directories found!", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Found site directories: {[str(d) for d in site_dirs]}")
        print(f"Python version: {sys.version}")

    
    num_processes = args.processes or cpu_count()

    if args.verbose:
        print(f"Using {num_processes} processes")

    all_pure_packages = []
    all_nonpure_packages = []

    with Pool(processes=num_processes) as pool:
        
        results = pool.map(find_packages_without_entry_points, site_dirs)

        
        for pure_pkgs, nonpure_pkgs in results:
            all_pure_packages.extend(pure_pkgs)
            all_nonpure_packages.extend(nonpure_pkgs)

    
    seen_pure = set()
    unique_pure = []
    for pkg in all_pure_packages:
        if pkg not in seen_pure:
            seen_pure.add(pkg)
            unique_pure.append(pkg)

    seen_nonpure = set()
    unique_nonpure = []
    for pkg in all_nonpure_packages:
        if pkg not in seen_nonpure:
            seen_nonpure.add(pkg)
            unique_nonpure.append(pkg)

    
    unique_pure.sort()
    unique_nonpure.sort()

    
    pure_output = args.pure_output
    nonpure_output = args.nonpure_output

    
    if args.output:
        
        combined = {
            "timestamp": datetime.now().isoformat(),
            "site_directories": [str(d) for d in site_dirs],
            "total_pure": len(unique_pure),
            "total_nonpure": len(unique_nonpure),
            "pure_packages": unique_pure,
            "non_pure_packages": unique_nonpure,
        }

        if args.json:
            Path(args.output).write_text(json.dumps(combined, indent=2))
        else:
            
            lines = []
            lines.append(f"Total pure Python packages: {len(unique_pure)}")
            lines.append(f"Total non-pure packages: {len(unique_nonpure)}")
            lines.append("")
            lines.append("=== PURE PYTHON PACKAGES ===")
            lines.extend(unique_pure)
            lines.append("")
            lines.append("=== NON-PURE PACKAGES ===")
            lines.extend(unique_nonpure)
            Path(args.output).write_text("\n".join(lines))

        if args.verbose:
            print(f"Combined results written to {args.output}")

    else:
        

        
        if args.json:
            pure_data = {
                "timestamp": datetime.now().isoformat(),
                "site_directories": [str(d) for d in site_dirs],
                "total": len(unique_pure),
                "packages": unique_pure,
            }
            Path(pure_output).write_text(json.dumps(pure_data, indent=2))
        else:
            Path(pure_output).write_text("\n".join(unique_pure))

        
        if args.json:
            nonpure_data = {
                "timestamp": datetime.now().isoformat(),
                "site_directories": [str(d) for d in site_dirs],
                "total": len(unique_nonpure),
                "packages": unique_nonpure,
            }
            Path(nonpure_output).write_text(json.dumps(nonpure_data, indent=2))
        else:
            Path(nonpure_output).write_text("\n".join(unique_nonpure))

    
    print(f"=== SUMMARY ===")
    print(f"Pure Python packages without entry_points.txt: {len(unique_pure)}")
    print(f"Non-pure packages without entry_points.txt: {len(unique_nonpure)}")
    print(f"Total: {len(unique_pure) + len(unique_nonpure)}")

    if args.verbose:
        print(f"\nPure packages written to: {pure_output}")
        print(f"Non-pure packages written to: {nonpure_output}")
        if unique_pure:
            print("\nFirst 5 pure packages:")
            for pkg in unique_pure[:5]:
                print(f"  {pkg}")
        if unique_nonpure:
            print("\nFirst 5 non-pure packages:")
            for pkg in unique_nonpure[:5]:
                print(f"  {pkg}")


if __name__ == "__main__":
    main()
