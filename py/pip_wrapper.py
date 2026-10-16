import re
import subprocess
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning)
try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:
    from importlib_metadata import PackageNotFoundError, version


def is_installed(pkg_name) -> bool | None:
    try:
        version(pkg_name)
        return True
    except PackageNotFoundError:
        return False


def uninstall_package(pkg_name) -> None:
    print(f"Uninstalling {pkg_name}...")
    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", pkg_name, "--verbose"],
        check=True,
    )


def whl_pkg_name(whl_path):
    whl_file = Path(whl_path).name
    match = re.match(r"([^\-]+)-[\d\.]+.*\.whl", whl_file)
    if match:
        return match.group(1).replace("_", "-").lower()
    return None


def pip_wrapper(args: list[str]) -> None:
    if not args:
        print("Error: No pip arguments provided.")
        sys.exit(1)
    verbose_flag = "--verbose"
    if verbose_flag not in args:
        args.append(verbose_flag)
    if "install" in args:
        pkg_names = []
        for arg in args:
            if arg.startswith("-"):
                continue
            if arg.endswith(".whl"):
                name = whl_pkg_name(arg)
                if name:
                    pkg_names.append(name.lower())
            else:
                pkg_names.append(arg.lower())
        to_remove = []
        for i, arg in enumerate(args):
            check_name = pkg_names[i] if i < len(pkg_names) else None
            if check_name and is_installed(check_name):
                print(f"{check_name} is already installed, skipping.")
                to_remove.append(arg)
        for arg in to_remove:
            args.remove(arg)
        if args == ["install", verbose_flag]:
            print("Nothing to install; all packages are already installed.")
            return
    elif "upgrade" in args:
        pkg_names = [arg for arg in args if not arg.startswith("-")]
        for pkg in pkg_names:
            if is_installed(pkg):
                uninstall_package(pkg)
    cmd = [sys.executable, "-m", "pip", *args, "--verbose"]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    pip_wrapper(sys.argv[1:])
