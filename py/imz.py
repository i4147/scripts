import ast
import multiprocessing as mp
import os
import tarfile
import zipfile
from pathlib import Path


def load_stdlib(path: str) -> set[str]:
    std = set()
    with Path(path).open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line:
                std.add(line)
    return std


def load_mapping(path: str) -> dict[str, str]:
    mapping = {}
    with Path(path).open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                mapping[k.strip()] = v.strip()
    return mapping


def load_offline_pip(path: str) -> set[str]:
    pkgs = set()
    with Path(path).open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            pkg = line.strip().lower()
            if pkg:
                pkgs.add(pkg)
    return pkgs


def extract_imports_from_py(code: str) -> set[str]:
    results = set()
    try:
        tree = ast.parse(code)
    except Exception:
        return results
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                results.add(root)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".", 1)[0]
            results.add(root)
    return results


def process_py_file(path: Path) -> set[str]:
    try:
        code = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return set()
    return extract_imports_from_py(code)


def process_zip_file(path: Path) -> set[str]:
    found = set()
    try:
        with zipfile.ZipFile(path, "r") as z:
            for name in z.namelist():
                if name.endswith(".py"):
                    try:
                        code = z.read(name).decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                    found |= extract_imports_from_py(code)
    except Exception:
        pass
    return found


def process_tar_file(path: Path) -> set[str]:
    found = set()
    mode = "r:xz" if str(path).endswith(".xz") else "r:gz"
    try:
        with tarfile.open(path, mode) as t:
            for member in t.getmembers():
                if member.isfile() and member.name.endswith(".py"):
                    try:
                        f = t.extractfile(member)
                        if not f:
                            continue
                        code = f.read().decode("utf-8", errors="ignore")
                        found |= extract_imports_from_py(code)
                    except Exception:
                        continue
    except Exception:
        pass
    return found


def process_any(path: str) -> set[str]:
    p = Path(path)
    if p.suffix == ".py":
        return process_py_file(p)
    if p.suffix in {".zip", ".whl"}:
        return process_zip_file(p)
    if str(p).endswith(".tar.gz") or str(p).endswith(".tgz"):
        return process_tar_file(p)
    if str(p).endswith(".tar.xz"):
        return process_tar_file(p)
    return set()


def scan_sources() -> list[str]:
    targets = []
    for root, _, files in os.walk("."):
        targets.extend(
            os.path.join(root, f) for f in files if f.endswith((".py", ".whl", ".zip", ".tar.gz", ".tgz", ".tar.xz"))
        )
    return targets


def resolve_packages(
    imports: set[str],
    stdlib: set[str],
    mapping: dict[str, str],
    pip: set[str],
) -> set[str]:
    results = set()
    for imp in imports:
        if imp in stdlib:
            continue
        name = mapping.get(imp, imp)
        if name.lower() in pip:
            results.add(name)
    return results


def main() -> None:
    stdlib = load_stdlib("stdlib")
    mapping = load_mapping("mapping")
    piplist = load_offline_pip("/sdcard/pip.txt")
    sources = scan_sources()
    with mp.Pool(mp.cpu_count()) as pool:
        all_import_sets = pool.map(process_any, sources)
    all_imports = set()
    for s in all_import_sets:
        all_imports |= s
    pkgs = resolve_packages(all_imports, stdlib, mapping, piplist)
    with Path("requirements.txt").open("w", encoding="utf-8") as f:
        f.writelines(pkg + "\n" for pkg in sorted(pkgs, key=str.lower))
    print("Generated requirements.txt")
    print(f"Found {len(pkgs)} packages.")


if __name__ == "__main__":
    main()
