import argparse
import compileall
import os
import pathlib
import shutil
import sys
import zipfile


def main() -> None:
    parser = argparse.ArgumentParser(description="Zip a Python package for Termux")
    parser.add_argument("package", help="Name of the package to zip")
    parser.add_argument(
        "-p",
        "--pyc",
        action="store_true",
        help="Store as compiled bytecode (.pyc) instead of source (.py)",
    )
    args = parser.parse_args()
    PYTHON_VERSION = "python3.12"
    SITE_PACKAGES = f"/data/data/com.termux/files/usr/lib/{PYTHON_VERSION}/site-packages"
    ZIP_DIR = f"/data/data/com.termux/files/usr/lib/{PYTHON_VERSION}/zipped-pkgs"
    pathlib.Path(ZIP_DIR).mkdir(exist_ok=True, parents=True)
    try:
        pkg_path = __import__(args.package).__file__.replace("__init__.py", "").replace(".py", "")
    except ImportError:
        print(f"Package {args.package} not found!")
        sys.exit(1)
    tmp_dir = f"/data/data/com.termux/files/usr/tmp/zip-pkg-{os.getpid()}"
    pathlib.Path(tmp_dir).mkdir(exist_ok=True, parents=True)
    if pkg_path.endswith(".py"):
        shutil.copy(pkg_path, f"{tmp_dir}/{args.package}.py")
        if args.pyc:
            compileall.compile_file(f"{tmp_dir}/{args.package}.py", force=True, quiet=1)
            pathlib.Path(f"{tmp_dir}/{args.package}.py").unlink()
            target_file = f"{args.package}.pyc"
        else:
            target_file = f"{args.package}.py"
        with zipfile.ZipFile(f"{ZIP_DIR}/{args.package}.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(f"{tmp_dir}/{target_file}", target_file)
        pathlib.Path(pkg_path).unlink()
    else:
        pkg_name_clean = pathlib.Path(pkg_path).name
        shutil.copytree(pkg_path, f"{tmp_dir}/{pkg_name_clean}")
        if args.pyc:
            compileall.compile_dir(f"{tmp_dir}/{pkg_name_clean}", force=True, quiet=1)
            for root, _, files in os.walk(f"{tmp_dir}/{pkg_name_clean}"):
                for file in files:
                    if file.endswith(".py"):
                        pathlib.Path(os.path.join(root, file)).unlink()
        with zipfile.ZipFile(f"{ZIP_DIR}/{args.package}.zip", "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(f"{tmp_dir}/{pkg_name_clean}"):
                for file in files:
                    zipf.write(
                        os.path.join(root, file),
                        os.path.relpath(os.path.join(root, file), tmp_dir),
                    )
        shutil.rmtree(pkg_path)
