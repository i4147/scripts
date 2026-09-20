
import os
import sys
import site
import subprocess
from pathlib import Path


try:
    from importlib.metadata import distributions, metadata
except ImportError:
    
    from importlib_metadata import distributions, metadata


def get_site_packages_dirs():
    system_dirs = []

    
    for path in sys.path:
        path_obj = Path(path)
        if path_obj.exists() and ("site-packages" in path or "dist-packages" in path):
            
            if not str(path_obj).startswith(str(Path.home())):
                system_dirs.append(path_obj)

    
    termux_prefix = Path("/data/data/com.termux/files/usr")
    if termux_prefix.exists():
        for lib_path in termux_prefix.glob("lib/python*/site-packages"):
            if lib_path.exists() and lib_path not in system_dirs:
                system_dirs.append(lib_path)

    
    try:
        user_dir = Path(site.getusersitepackages())
    except Exception:
        
        user_dir = (
            Path.home()
            / ".local"
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )

    
    system_dirs = list(set(system_dirs))

    return system_dirs, user_dir


def get_package_distributions(directory):
    packages = {}

    if not directory or not directory.exists():
        return packages

    
    dir_str = str(directory)

    try:
        
        for dist in distributions():
            
            dist_location = None

            
            if hasattr(dist, "_path"):
                dist_location = str(dist._path)
            elif hasattr(dist, "files") and dist.files:
                
                for file in dist.files:
                    try:
                        if hasattr(file, "locate"):
                            loc = str(file.locate())
                            if dir_str in loc:
                                dist_location = loc
                                break
                    except Exception:
                        continue

            
            if not dist_location:
                try:
                    if hasattr(dist, "metadata"):
                        meta = dist.metadata
                        if hasattr(meta, "get") and meta.get("Name"):
                            
                            try:
                                if hasattr(dist, "files"):
                                    for file in dist.files:
                                        try:
                                            loc = str(file.locate())
                                            if dir_str in loc:
                                                dist_location = loc
                                                break
                                        except Exception:
                                            continue
                            except Exception:
                                pass
                except Exception:
                    pass

            
            if dist_location and dir_str in dist_location:
                name = dist.metadata.get("Name", "Unknown")
                version = dist.metadata.get("Version", "Unknown")
                packages[name] = version

    except Exception as e:
        print(f"  Warning: Error scanning {directory}: {e}")

    return packages


def get_packages_with_pip(directory):
    packages = {}

    try:
        
        
        
        env = os.environ.copy()
        env["PYTHONPATH"] = str(directory)

        cmd = [sys.executable, "-m", "pip", "list", "--format", "json", "--local"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)

        if result.returncode == 0:
            import json

            data = json.loads(result.stdout)
            for pkg in data:
                packages[pkg["name"]] = pkg["version"]
    except Exception:
        pass

    return packages


def check_duplicate_packages():
    print("=" * 70)
    print("PYTHON PACKAGE DUPLICATE CHECKER (Python 3.13+)")
    print("=" * 70)
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")

    
    system_dirs, user_dir = get_site_packages_dirs()

    print(f"\nSystem site-packages directories:")
    for d in system_dirs:
        exists = "✅" if d.exists() else "❌"
        print(f"  {exists} {d}")

    print(f"\nUser site-packages directory:")
    exists = "✅" if user_dir.exists() else "❌"
    print(f"  {exists} {user_dir}")

    if not user_dir.exists():
        print("\n⚠️  No user site-packages directory found.")
        create_now = input("Create user site-packages directory? (y/n): ").lower().strip()
        if create_now == "y":
            user_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ Created: {user_dir}")
        else:
            print("Exiting.")
            return

    
    system_packages = {}
    print(f"\n📦 Scanning system directories...")

    for sys_dir in system_dirs:
        if not sys_dir.exists():
            continue
        print(f"  Scanning: {sys_dir.name}")
        sys_pkgs = get_package_distributions(sys_dir)

        
        if not sys_pkgs:
            sys_pkgs = get_packages_with_pip(sys_dir)

        system_packages.update(sys_pkgs)
        print(f"    Found {len(sys_pkgs)} packages")

    
    print(f"\n📦 Scanning user directory...")
    user_packages = get_package_distributions(user_dir)

    
    if not user_packages:
        user_packages = get_packages_with_pip(user_dir)

    print(f"    Found {len(user_packages)} packages")

    
    user_pkg_names = set(user_packages.keys())
    system_pkg_names = set(system_packages.keys())
    duplicate_names = user_pkg_names.intersection(system_pkg_names)

    
    duplicates = []
    for pkg_name in sorted(duplicate_names):
        duplicates.append(
            {
                "name": pkg_name,
                "system_version": system_packages.get(pkg_name, "Unknown"),
                "user_version": user_packages.get(pkg_name, "Unknown"),
            }
        )

    
    print("\n" + "=" * 70)
    print("📊 RESULTS")
    print("=" * 70)

    print(f"\nTotal system packages: {len(system_packages)}")
    print(f"Total user packages: {len(user_packages)}")
    print(f"Duplicate packages found: {len(duplicates)}")

    if duplicates:
        print("\n" + "-" * 70)
        print("⚠️  DUPLICATE PACKAGES:")
        print("-" * 70)

        
        print(f"{'Package':<35} {'System Version':<18} {'User Version':<18}")
        print("-" * 70)

        for pkg in duplicates:
            print(f"{pkg['name']:<35} {pkg['system_version']:<18} {pkg['user_version']:<18}")

        print("\n" + "-" * 70)
        print("💡 RECOMMENDATIONS:")
        print("-" * 70)
        print("1. To remove user version (keep system):")
        print(f"   pip uninstall --user <package-name>")
        print("\n2. To remove system version (keep user) - use with caution:")
        print(f"   pip uninstall <package-name> (may require sudo)")
        print("\n3. To upgrade user version to match system:")
        print(f"   pip install --user --upgrade <package-name>")
        print("\n4. Check which version is being imported:")
        print(f'   python -c "import <package>; print(<package>.__file__)"')

    else:
        print("\n✅ No duplicate packages found!")

    
    print("\n" + "=" * 70)
    print("📈 PACKAGE LOCATION SUMMARY:")
    print("=" * 70)
    print(f"Packages only in system: {len(system_pkg_names - user_pkg_names)}")
    print(f"Packages only in user: {len(user_pkg_names - system_pkg_names)}")
    print(f"Packages in both: {len(duplicate_names)}")

    
    if len(system_pkg_names - user_pkg_names) > 0:
        examples = list(sorted(system_pkg_names - user_pkg_names))[:5]
        print(f"\n  System-only examples: {', '.join(examples)}")

    if len(user_pkg_names - system_pkg_names) > 0:
        examples = list(sorted(user_pkg_names - system_pkg_names))[:5]
        print(f"  User-only examples: {', '.join(examples)}")

    
    print("\n" + "=" * 70)
    print("🔍 PYTHONPATH ANALYSIS:")
    print("=" * 70)
    for i, path in enumerate(sys.path, 1):
        is_user = "👤 USER" if str(Path.home()) in path else "💻 SYSTEM"
        exists = "✅" if Path(path).exists() else "❌"
        print(f"{i}. {is_user} {exists} {path}")

    print("\n" + "=" * 70)
    print("📝 NOTES:")
    print("=" * 70)
    print("• Python searches sys.path in order shown above")
    print("• The first matching package found is imported")
    print("• To modify PYTHONPATH, use: export PYTHONPATH=/path/to/your/dir:$PYTHONPATH")
    print("• To check import precedence: python -c 'import sys; print(sys.path)'")


def main():
    try:
        check_duplicate_packages()
    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
