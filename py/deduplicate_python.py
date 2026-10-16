import argparse
import ast
import hashlib
import multiprocessing as mp
import tarfile
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from loguru import logger

try:
    import tree_sitter_python
    from tree_sitter import Parser

    TREE_SITTER_AVAILABLE = True
except Exception:
    TREE_SITTER_AVAILABLE = False
try:
    import zstandard as zstd
except ImportError:
    zstd = None
try:
    import brotli
except ImportError:
    brotli = None


def sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed reading {path}: {e}")
        return None


def is_top_level(node):
    return node.parent and node.parent.type == "module"


def extract_with_tree_sitter(code: str):
    objects = []
    try:
        parser = Parser()
        parser.language(tree_sitter_python.language())
        tree = parser.parse(bytes(code, "utf8"))
        root = tree.root_node
        for node in root.children:
            if node.type in ("function_definition", "class_definition"):
                start = node.start_byte
                end = node.end_byte
                snippet = code[start:end]
                name_node = node.child_by_field_name("name")
                name = code[name_node.start_byte : name_node.end_byte]
                objects.append((name, snippet))
            elif node.type == "expression_statement":
                text = code[node.start_byte : node.end_byte]
                try:
                    parsed = ast.parse(text)
                    for n in parsed.body:
                        if isinstance(n, ast.Assign):
                            if all(isinstance(t, ast.Name) for t in n.targets):
                                name = n.targets[0].id
                                objects.append((name, text))
                except:
                    pass
    except Exception as e:
        logger.warning(f"Tree-sitter failed, fallback to ast: {e}")
        return extract_with_ast(code)
    return objects


def extract_with_ast(code: str):
    objects = []
    try:
        tree = ast.parse(code)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                snippet = ast.get_source_segment(code, node)
                objects.append((node.name, snippet))
            elif isinstance(node, ast.Assign):
                if all(isinstance(t, ast.Name) for t in node.targets):
                    snippet = ast.get_source_segment(code, node)
                    objects.append((node.targets[0].id, snippet))
    except Exception as e:
        logger.error(f"AST parsing failed: {e}")
    return objects


SUPPORTED_ARCHIVES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".gz",
    ".bz2",
    ".xz",
    ".zst",
    ".br",
)


def extract_archive(path: Path) -> str:
    temp_dir = tempfile.mkdtemp()
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                z.extractall(temp_dir)
        elif path.suffix in [".tar", ".gz", ".bz2", ".xz"] or any(
            str(path).endswith(ext) for ext in SUPPORTED_ARCHIVES
        ):
            with tarfile.open(path) as t:
                t.extractall(temp_dir)
        elif path.suffix == ".zst" and zstd:
            with open(path, "rb") as f:
                dctx = zstd.ZstdDecompressor()
                data = dctx.decompress(f.read())
                with open(Path(temp_dir) / path.stem, "wb") as out:
                    out.write(data)
        elif path.suffix == ".br" and brotli:
            with open(path, "rb") as f:
                data = brotli.decompress(f.read())
                with open(Path(temp_dir) / path.stem, "wb") as out:
                    out.write(data)
    except Exception as e:
        logger.error(f"Failed extracting {path}: {e}")
    return temp_dir


def collect_python_files(base: Path):
    files = []
    for path in base.rglob("*"):
        if path.is_file():
            if path.suffix == ".py":
                files.append(path)
            elif any(str(path).endswith(ext) for ext in SUPPORTED_ARCHIVES):
                extracted = extract_archive(path)
                files.extend(Path(extracted).rglob("*.py"))
    return files


def process_file(path: Path):
    code = safe_read(path)
    if not code:
        return []
    if TREE_SITTER_AVAILABLE:
        return extract_with_tree_sitter(code)
    else:
        return extract_with_ast(code)


def get_utils_path(base: Path) -> Path:
    utils = base / "utils.py"
    if not utils.exists():
        return utils
    i = 1
    while True:
        candidate = base / f"utils_{i}.py"
        if not candidate.exists():
            return candidate
        i += 1


def write_utils_file(path: Path, objects) -> bool:
    content = "\n\n".join(obj for _, obj in objects)
    try:
        ast.parse(content)
    except SyntaxError as e:
        logger.error(f"Syntax error in utils.py content: {e}")
        return False
    path.write_text(content, encoding="utf-8")
    return True


def add_imports_to_file(path: Path, names) -> None:
    try:
        code = safe_read(path)
        if not code:
            return
        import_line = f"from utils import ({', '.join(names)})\n"
        if import_line not in code:
            path.write_text(import_line + code, encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed updating imports in {path}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--move", action="store_true")
    parser.add_argument("-c", "--copy", action="store_true")
    args = parser.parse_args()
    base = Path(".").resolve()
    files = collect_python_files(base)
    with mp.Pool(mp.cpu_count()) as pool:
        results = pool.map(process_file, files)
    flat = [item for sublist in results for item in sublist]
    hash_map = defaultdict(list)
    for name, snippet in flat:
        h = sha256(snippet.strip())
        hash_map[h].append((name, snippet))
    duplicates = []
    for h, objs in hash_map.items():
        if len(objs) > 1:
            duplicates.append(objs[0])
    if not duplicates:
        logger.info("No duplicates found.")
        return
    if args.move or args.copy:
        utils_path = get_utils_path(base)
        if write_utils_file(utils_path, duplicates):
            logger.info(f"Written duplicates to {utils_path}")
            names = [name for name, _ in duplicates]
            for file in files:
                add_imports_to_file(file, names)
    logger.info(f"Found {len(duplicates)} duplicated objects.")


if __name__ == "__main__":
    main()
