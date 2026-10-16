import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

from dh import STDLIB, PKG_MAPPING


def normalize(name):
    return name.lower().replace("_", "-")


PKG_MAP_NORM = {normalize(k): v for k, v in PKG_MAPPING.items()}


def load_pypi_packages(path="/sdcard/data/pip.txt"):
    pypi = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            pypi.add(normalize(name))
    return pypi


def get_installed_packages(pip_version="pip"):
    installed_with_versions = []
    installed = set()
    try:
        stdout, _ = subprocess.Popen(
            [pip_version, "freeze"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).communicate()
    except FileNotFoundError:
        print("[!] '{}' not found, skipping installed-package check".format(pip_version))
        return installed_with_versions, installed

    for raw in stdout.splitlines():
        line = raw.decode("utf-8").strip()
        if not line or line.startswith("#") or line.startswith("-e"):
            continue
        installed_with_versions.append(line)
        name = line.split("==")[0].split("@")[0].strip()
        installed.add(normalize(name))
    return installed_with_versions, installed


def get_local_modules(directory):
    local = set()
    root = Path(directory).resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath)

        dirnames[:] = [
            d
            for d in dirnames
            if d
            not in {
                "__pycache__",
                "venv",
                ".venv",
                "env",
                ".env",
                ".git",
                ".hg",
                ".svn",
                "node_modules",
                "build",
                "dist",
                ".eggs",
            }
            and not d.endswith(".egg-info")
            and not d.startswith(".")
        ]

        if "__init__.py" in filenames:
            local.add(normalize(dirpath.name))

        for fn in filenames:
            if fn.endswith(".py"):
                if fn in {"setup.py", "conftest.py", "__init__.py"}:
                    continue
                local.add(normalize(fn[:-3]))

    if root.name and root.name not in {".", "/"}:
        local.add(normalize(root.name))

    return local


def extract_imports_from_lines(lines):
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words = stripped.split()
        if not words:
            continue
        if words[0] == "import":
            for part in " ".join(words[1:]).split(","):
                token = part.strip().split(" as ")[0].strip()
                if token:
                    yield token.split(".")[0]
        elif words[0] == "from":
            if len(words) < 2 or words[1].startswith("."):
                continue
            token = words[1].strip().split(".")[0]
            if token:
                yield token


def get_project_imports(directory=os.curdir):
    modules = []
    seen = set()
    for root, dirnames, files in os.walk(directory):
        dirnames[:] = [
            d
            for d in dirnames
            if d
            not in {
                "__pycache__",
                "venv",
                ".venv",
                "env",
                ".env",
                ".git",
                ".hg",
                ".svn",
                "node_modules",
                "build",
                "dist",
                ".eggs",
            }
            and not d.endswith(".egg-info")
        ]
        for name in files:
            full = os.path.join(root, name)
            if name.endswith(".py"):
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                except OSError:
                    continue
                for mod in extract_imports_from_lines(lines):
                    if mod not in seen:
                        seen.add(mod)
                        modules.append(mod)
                        print("found {} in {}".format(mod, name))

            elif name.endswith(".ipynb"):
                try:
                    contents = json.loads(Path(full).absolute().read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                for cell in contents.get("cells", []):
                    for mod in extract_imports_from_lines(cell.get("source", [])):
                        if mod not in seen:
                            seen.add(mod)
                            modules.append(mod)
                            print("found {} in {}".format(mod, name))
    return modules


def resolve_package_name(import_name):
    norm = normalize(import_name)
    mapped = PKG_MAP_NORM.get(norm)
    if mapped:
        return mapped, True
    return import_name, False


def init(args):
    pypi_index = load_pypi_packages(args["pypi_list"])
    print("[i] Loaded {} packages from {}".format(len(pypi_index), args["pypi_list"]))
    print("[i] Loaded {} import->package mappings".format(len(PKG_MAP_NORM)))

    target = args["path"] if args["path"] else os.curdir

    local_modules = get_local_modules(target)
    print("[i] Detected {} local modules/packages".format(len(local_modules)))

    modules = get_project_imports(target)
    print("[i] Found {} unique imports in source".format(len(modules)))

    pip_cmd = args["version"] if args["version"] else "pip3"
    installed_with_versions, installed = get_installed_packages(pip_cmd)
    print("[i] {} packages installed locally".format(len(installed)))

    stdlib_set = {normalize(m) for m in STDLIB}
    output_text = []
    skipped_stdlib = []
    skipped_installed = []
    skipped_local = []
    missing = []
    mapped_count = 0

    for mod in modules:
        norm = normalize(mod)

        if norm in stdlib_set:
            skipped_stdlib.append(mod)
            continue

        if norm in local_modules:
            skipped_local.append(mod)
            continue

        pkg_name, was_mapped = resolve_package_name(mod)
        pkg_norm = normalize(pkg_name)

        if pkg_norm in installed or norm in installed:
            skipped_installed.append(mod)
            continue

        if pkg_norm in pypi_index:
            if was_mapped:
                mapped_count += 1
                print("[→] {} -> {}".format(mod, pkg_name))
            output_text.append(pkg_name)
        elif norm in pypi_index:
            output_text.append(mod)
        else:
            missing.append(mod)

    print("\n[i] Skipped {} stdlib modules".format(len(skipped_stdlib)))
    print("[i] Skipped {} local modules: {}".format(len(skipped_local), ", ".join(sorted(skipped_local)) or "-"))
    print("[i] Skipped {} already-installed modules".format(len(skipped_installed)))
    print("[i] Resolved {} renamed packages (import != pkg)".format(mapped_count))
    if missing:
        print("[i] Skipped {} unknown modules: {}".format(len(missing), ", ".join(sorted(missing))))

    out_dir = args["path"] if args["path"] else os.curdir
    out_file = os.path.join(out_dir, "requirements.txt")
    unique = sorted(set(output_text))
    with open(out_file, "w", encoding="utf-8") as f:
        if unique:
            f.write("\n".join(unique) + "\n")

    print("\n[✓] Wrote {} packages to {}".format(len(unique), out_file))


def main():
    ap = argparse.ArgumentParser(description="Offline requirements.txt generator")
    ap.add_argument("-v", "--version", type=str, help="Pip command to use (default: pip3)")
    ap.add_argument("-p", "--path", type=str, help="Path to target project directory")
    ap.add_argument(
        "-l",
        "--pypi-list",
        type=str,
        default="/sdcard/data/pip.txt",
        help="Path to offline PyPI package list (default: /sdcard/data/pip.txt)",
    )
    args = vars(ap.parse_args())
    try:
        init(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
