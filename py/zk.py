import compileall
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import dh
import importlib_metadata

site_dir = Path("/data/data/com.termux/files/usr/lib/python3.12/site-packages")


def get_pkgs():
    pkgs = []
    for pkg in importlib_metadata.distributions():
        pkgname = pkg.metadata["name"].lower().replace("-", "_")
        pkgs.append(pkgname)
    return pkgs


def get_toplevel(pkg):
    found = []
    for k in importlib_metadata._top_level_infered(pkg):
        found.append(k)
    return found


CYAN = "\033[0;96m"
GREEN = "\033[0;92m"
YELLOW = "\033[1;93m"
RED = "\033[0;91m"
NC = "\033[0m"


def print_info(msg) -> None:
    print(f"{CYAN}{msg}{NC}")


def print_success(msg) -> None:
    print(f"{GREEN}✓ {msg}{NC}")


def print_warning(msg) -> None:
    print(f"{YELLOW}{msg}{NC}")


def print_error(msg: str) -> None:
    print(f"{RED}✗ {msg}{NC}")


def get_package_path(pkg_name) -> str | None:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import {pkg_name}; print({pkg_name}.__file__)",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            if path.endswith("__init__.py"):
                return str(Path(path).parent)
            if path.endswith(".py"):
                return path
            return path
    except Exception as e:
        print_error(f"Error importing {pkg_name}: {e}")
    return None


def is_single_file_module(pkg_path):
    return pkg_path.endswith(".py")


def is_package_directory(pkg_path) -> bool:
    if not Path(pkg_path).is_dir():
        return False
    py_files = dh.get_files(pkg_path, extensions=[".py"])
    return len(py_files) > 1


def compile_to_bytecode(directory) -> bool:
    try:
        compileall.compile_dir(directory, legacy=True, optimize=2)
        dirpath = Path(directory)
        for pyfile in dirpath.rglob("*.py"):
            pyfile.unlink()
        for dir_path in Path(directory).rglob("__pycache__"):
            shutil.rmtree(str(dir_path))
        return True
    except Exception as e:
        print_error(f"Compilation failed: {e}")
        return False


def have_so(directory) -> bool:
    return any(str(path).endswith(".so") for path in directory.rglob("*"))


def create_zip(src_path, zip_path) -> bool:
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if Path(src_path).is_file():
                arcname = Path(src_path).name
                zf.write(src_path, arcname)
            else:
                for root, _dirs, files in os.walk(src_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(
                            file_path,
                            Path(src_path).parent,
                        )
                        zf.write(file_path, arcname)
        return True
    except Exception as e:
        print_error(f"Failed to create zip: {e}")
        return False


def process_pkg(pkgname) -> None:
    pkg_path = get_toplevel(pkgname)
    if len(pkg_path) > 1:
        print(f"{pkgname} have more than one top level dir.")
        return
    if is_single_file_module(pkg_path) or have_so(pkg_path):
        print(f"{pkg_path} have .so file or is a single file midule")
        return
    zip_dir = site_dir
    zip_path = Path(f"{zip_dir}/{pkg_path}.zip")
    if zip_path.exists():
        print("already zipped.")
        return


def main(args) -> None:
    if args:
        pkgs = list(args)
        installed = get_pkgs()
        for pkg in pkgs:
            if pkg in installed:
                process_pkg(pkg)
    else:
        sys.exit(0)


if __name__ == "__main__":
    sys.exit(main(args=sys.argv[1:]))
"""
def main():
    parser = argparse.ArgumentParser(description="Convert Python packages to zipped format for efficient storage")
    parser.add_argument("package", help="Package name to zip")
    parser.add_argument(
        "-p", "--pyc", action="store_true", help="Store as compiled bytecode (.pyc) instead of source (.py)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()
    pkg_name = args.package
    use_pyc = args.pyc
    print_info(f"Processing package: {pkg_name}...")
    pkg_path = get_package_path(pkg_name)
    if not pkg_path:
        print_error(f"Package '{pkg_name}' not found!")
        sys.exit(1)
    if args.verbose:
        print_info(f"Package path: {pkg_path}")
    if is_single_file_module(pkg_path):
        print_warning(f"Skipping '{pkg_name}' - single file modules are not supported")
        sys.exit(0)
    if have_so_file(pkg_path):
        print("have .so file")
        sys.exit(0)
    if not is_package_directory(pkg_path):
        print_warning(f"Skipping '{pkg_name}' - not a multi-file package")
        sys.exit(0)
    site_packages = get_site_packages()
    zip_dir = site_packages
    os.makedirs(zip_dir, exist_ok=True)
    zip_path = os.path.join(zip_dir, f"{pkg_name}.zip")
    if os.path.exists(zip_path):
        print_warning(f"{pkg_name}.zip already exists. Overwriting...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        print_warning("Step 1: Preparing package...")
        tmp_pkg_path = os.path.join(tmp_dir, os.path.basename(pkg_path))
        shutil.copytree(pkg_path, tmp_pkg_path)
        if use_pyc:
            print_warning("Compiling to bytecode...")
            if not compile_to_bytecode(tmp_pkg_path):
                sys.exit(1)
        so_files = find_so_files(tmp_pkg_path)
        if so_files:
            print_warning("C extensions detected. Keeping in site-packages...")
            for so_file in so_files:
                rel_path = os.path.relpath(so_file, tmp_pkg_path)
                if args.verbose:
                    print_info(f"Excluding: {rel_path}")
                os.remove(so_file)
        print_warning("Step 2: Creating zip archive...")
        if not create_zip(tmp_pkg_path, zip_path, pkg_name):
            sys.exit(1)
        original_size = sum(
            os.path.getsize(os.path.join(dirpath, filename))
            for dirpath, dirnames, filenames in os.walk(pkg_path)
            for filename in filenames
        )
        compressed_size = os.path.getsize(zip_path)
        compression_ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
        print_warning("Step 3: Creating loader stub...")
        loader_path = os.path.join(site_packages, f"{pkg_name}.py")
        loader_code = f
import sys, os
ZIP_PATH = os.path.join(r'{zip_dir}', r'{pkg_name}.zip')
if ZIP_PATH not in sys.path: sys.path.insert(0, ZIP_PATH)
module = __import__(r'{pkg_name}')
sys.modules[r'{pkg_name}'] = module
        try:
            with open(loader_path, "w") as f:
                f.write(loader_code)
        except Exception as e:
            print_error(f"Failed to create loader stub: {e}")
            sys.exit(1)
        try:
            shutil.rmtree(pkg_path)
        except Exception as e:
            print_error(f"Failed to remove original package: {e}")
            sys.exit(1)
    mode = ".pyc" if use_pyc else ".py"
    size_mb = compressed_size / (1024 * 1024)
    original_mb = original_size / (1024 * 1024)
    print_success(f"{pkg_name} zipped successfully")
    print_info(f"Mode: {mode}")
    print_info(f"Original size: {original_mb:.2f} MB")
    print_info(f"Compressed size: {size_mb:.2f} MB")
    print_info(f"Compression ratio: {compression_ratio:.1f}%")
    print_info(f"Saved to: {zip_path}")
if __name__ == "__main__":
    main()
def get_site_packages():
    site_packages = get_path("purelib")
    if not site_packages:
        site_packages = os.path.join(
            os.path.dirname(sys.executable),
            f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages",
        )
    return site_packages
"""
