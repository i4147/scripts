import ast
import multiprocessing as mp
import os
import tarfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

DEFAULT_STDLIB_FILE = "stdlib.txt"
DEFAULT_MAPPING_FILE = "mapping.txt"
DEFAULT_PIP_LIST_FILE = "/sdcard/data/pip.txt"
OUTPUT_FILE = "requirements.txt"
MODULE_MAPPINGS = {}


def load_mappings(mapping_file: str = DEFAULT_MAPPING_FILE) -> dict[str, str]:
    mappings = {}
    if Path(mapping_file).exists():
        try:
            with Path(mapping_file).open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and ":" in line and (not line.startswith("#")):
                        imported, package = line.split(":", 1)
                        imported = imported.strip()
                        package = package.strip()
                        if imported and package:
                            mappings[imported] = package
        except Exception:
            pass
    return mappings


STDLIB_MODULES = set()


def load_stdlib_modules(stdlib_file: str = DEFAULT_STDLIB_FILE) -> set[str]:
    modules = set()
    if Path(stdlib_file).exists():
        try:
            with Path(stdlib_file).open("r", encoding="utf-8") as f:
                for line in f:
                    module = line.strip()
                    if module and (not module.startswith("#")):
                        modules.add(module)
        except Exception:
            pass
    return modules


def load_pypi_packages(pip_file: str = DEFAULT_PIP_LIST_FILE) -> set[str]:
    packages = set()
    if Path(pip_file).exists():
        try:
            with Path(pip_file).open("r", encoding="utf-8") as f:
                for line in f:
                    package = line.strip()
                    if package and (not package.startswith("#")):
                        package = package.split("==")[0].split(">=")[0].split("<=")[0]
                        packages.add(package.lower())
        except Exception:
            pass
    return packages


def is_relative_import(module_name: str) -> bool:
    return module_name.startswith(".")


def extract_imports_from_code(code: str, filepath: str = "") -> set[str]:
    imports = set()
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name and (not is_relative_import(module_name)):
                        imports.add(module_name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]
                    if module_name and (not is_relative_import(module_name)):
                        imports.add(module_name)
    except SyntaxError:
        pass
    except Exception:
        pass
    return imports


def extract_imports_from_file(filepath: str) -> set[str]:
    try:
        content = Path(filepath).read_text(encoding="utf-8")
        return extract_imports_from_code(content, filepath)
    except UnicodeDecodeError:
        try:
            content = Path(filepath).read_text(encoding="latin-1")
            return extract_imports_from_code(content, filepath)
        except Exception:
            return set()
    except Exception:
        return set()


def is_python_file(filepath: str) -> bool:
    name = Path(filepath).name
    if name.endswith(".py"):
        return True
    if "." not in name:
        try:
            with Path(filepath).open("r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line.startswith("#!") and "python" in first_line.lower():
                    return True
                if first_line.strip().startswith(("import ", "from ", "def ", "class ", "async ")):
                    return True
        except:
            pass
    return False


def extract_imports_from_zip(zip_path: str) -> set[str]:
    imports = set()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for file_info in zf.infolist():
                if file_info.filename.endswith(".py"):
                    try:
                        with zf.open(file_info) as f:
                            content = f.read().decode("utf-8", errors="ignore")
                            file_imports = extract_imports_from_code(content, f"{zip_path}/{file_info.filename}")
                            imports.update(file_imports)
                    except:
                        continue
    except Exception:
        pass
    return imports


def extract_imports_from_tar(tar_path: str) -> set[str]:
    imports = set()
    try:
        with tarfile.open(tar_path, "r:*") as tf:
            for member in tf.getmembers():
                if member.name.endswith(".py") and member.isfile():
                    try:
                        f = tf.extractfile(member)
                        if f:
                            content = f.read().decode("utf-8", errors="ignore")
                            file_imports = extract_imports_from_code(content, f"{tar_path}/{member.name}")
                            imports.update(file_imports)
                    except:
                        continue
    except Exception:
        pass
    return imports


def extract_imports_from_archive(filepath: str) -> set[str]:
    if filepath.endswith((".zip", ".whl")):
        return extract_imports_from_zip(filepath)
    if filepath.endswith((".tar.gz", ".tgz", ".tar.xz", ".txz")):
        return extract_imports_from_tar(filepath)
    if filepath.endswith((".tar.zst", ".tzst", ".tar")):
        return extract_imports_from_tar(filepath)
    return set()


def process_file(filepath: str) -> set[str]:
    imports = set()
    if is_python_file(filepath):
        imports = extract_imports_from_file(filepath)
    elif any(
        (
            filepath.endswith(ext)
            for ext in [".zip", ".whl", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.zst", ".tzst", ".tar"]
        )
    ):
        imports = extract_imports_from_archive(filepath)
    return imports


def find_files(directory: str) -> list[str]:
    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", ".venv", "venv", "env", "node_modules"}]
        for filename in filenames:
            filepath = os.path.join(root, filename)
            if is_python_file(filepath) or any(
                (
                    filepath.endswith(ext)
                    for ext in [".zip", ".whl", ".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.zst", ".tzst", ".tar"]
                )
            ):
                files.append(filepath)
    return files


def filter_and_map_imports(
    imports: set[str], stdlib_modules: set[str], module_mappings: dict[str, str], pypi_packages: set[str]
) -> set[str]:
    filtered = set()
    for imp in imports:
        if imp in stdlib_modules:
            continue
        if pypi_packages and imp.lower() not in pypi_packages:
            for pkg in pypi_packages:
                if imp.lower() == pkg or imp.replace("_", "-").lower() == pkg:
                    filtered.add(pkg)
                    break
            else:
                filtered.add(imp)
        else:
            filtered.add(imp)
    mapped = set()
    for imp in filtered:
        if imp in module_mappings:
            mapped.add(module_mappings[imp])
        else:
            mapped.add(imp)
    return mapped


def extract_requirements(
    directory: str = ".",
    stdlib_file: str = DEFAULT_STDLIB_FILE,
    mapping_file: str = DEFAULT_MAPPING_FILE,
    pip_file: str = DEFAULT_PIP_LIST_FILE,
    output_file: str = OUTPUT_FILE,
    use_multiprocessing: bool = True,
) -> None:
    stdlib_modules = load_stdlib_modules(stdlib_file)
    module_mappings = load_mappings(mapping_file)
    pypi_packages = load_pypi_packages(pip_file)
    all_files = find_files(directory)
    if not all_files:
        return
    all_imports = set()
    if use_multiprocessing and len(all_files) > 10:
        with ProcessPoolExecutor(max_workers=mp.cpu_count()) as executor:
            futures = {executor.submit(process_file, f): f for f in all_files}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                if completed % 100 == 0:
                    pass
                try:
                    imports = future.result()
                    all_imports.update(imports)
                except Exception:
                    filepath = futures[future]
    else:
        for i, filepath in enumerate(all_files):
            if i % 100 == 0:
                pass
            imports = process_file(filepath)
            all_imports.update(imports)
    requirements = filter_and_map_imports(all_imports, stdlib_modules, module_mappings, pypi_packages)
    sorted_requirements = sorted(requirements)
    with Path(output_file).open("w", encoding="utf-8") as f:
        f.writelines((f"{req}\n" for req in sorted_requirements))
    for _req in sorted_requirements[:20]:
        pass
    if len(sorted_requirements) > 20:
        pass


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Extract Python package requirements from Python files recursively.")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to scan (default: current directory)")
    parser.add_argument(
        "--stdlib", default=DEFAULT_STDLIB_FILE, help=f"Path to stdlib.txt file (default: {DEFAULT_STDLIB_FILE})"
    )
    parser.add_argument(
        "--mapping", default=DEFAULT_MAPPING_FILE, help=f"Path to mapping.txt file (default: {DEFAULT_MAPPING_FILE})"
    )
    parser.add_argument(
        "--pip-list", default=DEFAULT_PIP_LIST_FILE, help=f"Path to pip.txt file (default: {DEFAULT_PIP_LIST_FILE})"
    )
    parser.add_argument("--output", default=OUTPUT_FILE, help=f"Output file (default: {OUTPUT_FILE})")
    parser.add_argument("--no-mp", action="store_true", help="Disable multiprocessing")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    args = parser.parse_args()
    extract_requirements(
        directory=args.directory,
        stdlib_file=args.stdlib,
        mapping_file=args.mapping,
        pip_file=args.pip_list,
        output_file=args.output,
        use_multiprocessing=not args.no_mp,
    )


if __name__ == "__main__":
    main()
