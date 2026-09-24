import ast
import importlib.metadata
import importlib.util
import numbers
import sys
import time
from collections import defaultdict
from pathlib import Path


try:
    from joblib import Parallel, delayed

    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

from dh import STDLIB, get_files, get_installed_pkgs


class ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.imports = set()

    def visit_Import(self, node) -> None:
        for node_name in node.names:
            self.imports.add(node_name.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node) -> None:
        if node.level == 0 and node.module:
            self.imports.add(node.module.split(".")[0])
        self.generic_visit(node)


def get_local_packages(start_path: Path) -> set:
    packages = set()
    for init_file in start_path.rglob("__init__.py"):
        packages.add(init_file.parent.name)
    return packages


def _process_file(file_path: Path) -> tuple:
    imports = set()
    error = None
    try:
        code = file_path.read_text(encoding="utf-8")
        tree = ast.parse(code)
        visitor = ImportVisitor()
        visitor.visit(tree)
        imports = visitor.imports
    except SyntaxError as e:
        error = f"SyntaxError: {e}"
    except UnicodeDecodeError as e:
        error = f"UnicodeDecodeError: {e}"
    except Exception as e:
        error = f"Error: {e}"

    return (file_path, imports, error is None, error)


def find_imports(start_path: Path):
    files = get_files(start_path, ext=[".py"])

    files_by_dir = defaultdict(list)
    for f in files:
        try:
            rel_path = f.relative_to(start_path)

            if len(rel_path.parts) > 1:
                subdir = rel_path.parts[0]
            else:
                subdir = "."
        except ValueError:
            subdir = str(f.parent)
        files_by_dir[subdir].append(f)

    show_progress = len(files_by_dir) > 50

    all_imports = set()

    if show_progress:
        print(f"\nProcessing {len(files_by_dir)} directories with {len(files)} total files...")
        print("=" * 60)

    dir_count = 0
    for subdir, dir_files in sorted(files_by_dir.items()):
        dir_count += 1

        if show_progress:
            start_time = time.time()

        if HAS_JOBLIB:
            results = Parallel(n_jobs=-1)(delayed(_process_file)(f) for f in dir_files)
            for file_path, imports, success, error in results:
                if success:
                    all_imports.update(imports)
        else:
            for f in dir_files:
                file_path, imports, success, error = _process_file(f)
                if success:
                    all_imports.update(imports)

        if show_progress:
            elapsed = time.time() - start_time
            print(f"[{dir_count}/{len(files_by_dir)}] {subdir:<30} ({len(dir_files):>4} files, {elapsed:.2f}s)")

    if show_progress:
        print("=" * 60)
        print(f"Total processing time: {sum(time.time() - start_time for _ in [1]) if not show_progress else ''}")
        print()

    std_libs = STDLIB

    local_modules = {p.stem for p in start_path.glob("*.py")}
    local_packages = get_local_packages(start_path)
    local_names = local_modules | local_packages

    result = sorted(
        [
            imp
            for imp in all_imports
            if imp not in std_libs and imp not in local_names and not imp.startswith(".") and imp != "__future__"
        ]
    )
    return result


def get_version(module_name) -> str:
    try:
        return importlib.metadata.version(module_name)
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return "Not Installed"
        mod = importlib.import_module(module_name)
        for k, v in mod.__dict__.items():
            if ("version" in k.lower() or "ver" in k.lower()) and isinstance(v, (str, numbers.Number)):
                return str(v)
    except Exception:
        return "Not Installed(unknown)"
    return "Not Installed(NA)"


def main() -> None:
    overall_start = time.time()
    cwd = Path.cwd()
    sys.argv[1:]
    output_file = cwd / "requirements.txt"

    print(f"Scanning directory: {cwd}")
    modules = find_imports(cwd)

    if not modules:
        print("No third-party imports found.")
        return

    results = []
    print(f"\n{'Module':<20} | {'Version':<15}")
    print("-" * 40)
    for mod in modules:
        if mod.startswith("_"):
            continue
        ver = get_version(mod)
        line = f"{mod:<20} | {ver:<15}"
        print(line)
        if "Not Installed" in ver:
            results.append(f"{mod}=={ver}")

    if results:
        Path(output_file).write_text("\n".join(results), encoding="utf-8")
        cleaned = []
        with Path(output_file).open(encoding="utf-8") as fin:
            lines = fin.readlines()
            cleaned.extend(
                (
                    line.rstrip()
                    .replace("Not Installed", "")
                    .replace("==(NA)", "")
                    .replace("==(unknown)", "")
                    .replace("==", "")
                    for line in lines
                )
            )
        pkgz = get_installed_pkgs()
        cleaned = [p for p in cleaned if p not in pkgz and (not p.startswith("_"))]
        if cleaned:
            with output_file.open("w", encoding="utf-8") as f:
                f.write("\n".join(cleaned))
            print(f"\n✅ Created {output_file}")
        else:
            if output_file.exists():
                output_file.unlink()
            print(f"\n❌ empty {output_file} removed (all packages already installed)")
    else:
        if output_file.exists():
            output_file.unlink()
        print("\n✅ No uninstalled packages found")

    overall_elapsed = time.time() - overall_start
    if overall_elapsed > 1.0:
        print(f"\n⏱️  Total time: {overall_elapsed:.2f}s")


if __name__ == "__main__":
    main()
