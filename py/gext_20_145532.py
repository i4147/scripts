from __future__ import annotations

import ast
import re
import sys
import tarfile
import zipfile
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dh import get_files


try:
    import tree_sitter_python as tsp
    from tree_sitter import Language, Parser

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False
try:
    import zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        new_path = path.with_name(f"{stem}_{counter}{suffix}")
        if not new_path.exists():
            return new_path
        counter += 1


HERE = "-t" in sys.argv
if not HERE:
    OUTPUT_DIR = Path.cwd() / "output"
else:
    OUTPUT_DIR = Path.home() / "tmp" / "output"
ARCHIVE_EXTENSIONS = (
    ".whl",
    ".zip",
    ".tar.gz",
    ".tgz",
    ".tar.zst",
    ".tar.xz",
    ".tar",
    ".zst",
)
ALLOWED_PYTHON_EXTENSIONS = ".py"
COMMON_IMPORTS = {
    "typing": [
        "List",
        "Dict",
        "Optional",
        "Union",
        "Tuple",
        "Any",
        "Callable",
        "TypeVar",
    ],
    "dataclasses": ["dataclass", "field"],
    "enum": ["Enum", "auto"],
    "abc": ["ABC", "abstractmethod"],
    "pathlib": ["Path", "PurePath"],
    "datetime": ["datetime", "date", "timedelta", "time"],
    "collections": ["defaultdict", "Counter", "deque", "OrderedDict"],
    "itertools": ["chain", "cycle", "product", "permutations", "combinations"],
    "functools": ["lru_cache", "wraps", "partial", "reduce"],
    "typing_extensions": ["Literal", "TypedDict", "Protocol"],
}
IMPORT_PATTERNS = {
    r"\bList\b|\bDict\b|\bOptional\b|\bUnion\b|\bTuple\b|\bAny\b|\bCallable\b": "from typing import List, Dict, Optional, Union, Tuple, Any, Callable",
    r"\bTypeVar\b": "from typing import TypeVar",
    "@dataclass": "from dataclasses import dataclass",
    r"\bEnum\b": "from enum import Enum",
    r"\bABC\b|\babstractmethod\b": "from abc import ABC, abstractmethod",
    r"\bPath\b(?!\.)": "from pathlib import Path",
    r"\bdatetime\b": "from datetime import datetime",
    r"\bre\.|re\.": "import re",
    r"\bjson\.": "import json",
    r"\blogging\.|getLogger": "import logging",
    r"\bos\.": "import os",
    r"\bsys\.": "import sys",
    r"\bmath\.": "import math",
    r"\brandom\.": "import random",
    r"\bdefaultdict\b|\bCounter\b|\bdeque\b": "from collections import defaultdict, Counter, deque",
    r"\bchain\b|\bcycle\b|\bproduct\b": "from itertools import chain, cycle, product",
    r"\blru_cache\b|\bwraps\b": "from functools import lru_cache, wraps",
    r"\bLiteral\b|\bTypedDict\b|\bProtocol\b": "from typing_extensions import Literal, TypedDict, Protocol",
    "@property": "from functools import property",
    "@staticmethod": "import staticmethod",
    "@classmethod": "import classmethod",
}


class EntityExtractor(ast.NodeVisitor):
    def __init__(self, source_content: str, original_path: Path) -> None:
        self.entities = []
        self.source_lines = source_content.splitlines(keepends=True)
        self.original_path = original_path
        self.scope_stack = []
        self.imports = set()
        self.imports_from = {}
        self.source_content = source_content

    def _get_source_slice(self, node: ast.AST) -> str:
        start_line = node.lineno - 1
        end_line = node.end_lineno or node.lineno
        code_slice = self.source_lines[start_line:end_line]
        if node.col_offset is not None and code_slice:
            code_slice[0] = code_slice[0][node.col_offset :]
        if node.end_col_offset is not None and node.end_col_offset > 0 and code_slice:
            last_line = code_slice[-1]
            code_slice[-1] = last_line[: node.end_col_offset]
        return "".join(code_slice)

    def _extract_and_save(self, node: ast.AST, entity_type: str, name: str) -> None:
        entity_code = self._get_source_slice(node)
        scope_prefix = "_".join(self.scope_stack)
        full_name = f"{scope_prefix}_{name}" if scope_prefix else name
        self.entities.append(
            {
                "name": name,
                "full_name": full_name,
                "type": entity_type,
                "code": entity_code,
                "path": str(self.original_path),
                "is_constant": entity_type == "const",
                "is_class": entity_type == "class",
                "is_function": entity_type in ("function", "method"),
                "imports": list(self.imports),
                "imports_from": self.imports_from.copy(),
            }
        )

    def _add_import(self, import_stmt: str) -> None:
        self.imports.add(import_stmt)

    def _add_import_from(self, module: str, names: list[str]) -> None:
        if module not in self.imports_from:
            self.imports_from[module] = set()
        for name in names:
            self.imports_from[module].add(name)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add_import(f"import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        names = [alias.name for alias in node.names]
        self._add_import_from(module, names)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        entity_type = "method" if self.scope_stack and self.scope_stack[-1].startswith("class_") else "function"
        if entity_type == "function":
            self._extract_and_save(node, entity_type, node.name)
            self.scope_stack.append(f"func_{node.name}")
            self.generic_visit(node)
            self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        entity_type = "method" if self.scope_stack and self.scope_stack[-1].startswith("class_") else "function"
        if entity_type == "function":
            self._extract_and_save(node, entity_type, node.name)
            self.scope_stack.append(f"async_func_{node.name}")
            self.generic_visit(node)
            self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._extract_and_save(node, "class", node.name)
        self.scope_stack.append(f"class_{node.name}")
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.scope_stack and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            if re.match("^[A-Z_][A-Z0-9_]*$", target_name):
                self._extract_and_save(node, "const", target_name)


class ImportCollector:
    VALID_IMPORT_TYPES = {"import_statement", "import_from_statement"}

    @staticmethod
    def parse_imports_with_tree_sitter(content: bytes) -> list[str]:
        if not HAS_TREE_SITTER:
            return []
        parser = Parser()
        parser.language = Language(tsp.language())
        try:
            tree = parser.parse(content)
            root = tree.root_node
            imports = []
            for node in root.children:
                if node.type in ImportCollector.VALID_IMPORT_TYPES:
                    import_text = content[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
                    if not import_text.startswith("from ."):
                        imports.append(import_text)
            return imports
        except Exception as e:
            print(f"Tree-sitter parsing error: {e}")
            return []

    @staticmethod
    def parse_imports_with_ast(content: str) -> list[str]:
        imports = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(f"import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (not node.module.startswith(".")):
                        names = ", ".join([alias.name for alias in node.names])
                        imports.append(f"from {node.module} import {names}")
        except:
            pass
        return imports

    @staticmethod
    def collect_from_file(file_path: Path) -> list[str]:
        try:
            content_bytes = file_path.read_bytes()
            content_str = content_bytes.decode("utf-8", errors="ignore")
            imports = ImportCollector.parse_imports_with_tree_sitter(content_bytes)
            if not imports:
                imports = ImportCollector.parse_imports_with_ast(content_str)
            return imports
        except Exception as e:
            print(f"Error collecting imports from {file_path}: {e}")
            return []


def analyze_dependencies(code: str) -> set[str]:
    imports = set()
    for pattern, imp in IMPORT_PATTERNS.items():
        if re.search(pattern, code, re.MULTILINE):
            imports.add(imp)
    typing_types = re.findall("\\b(List|Dict|Optional|Union|Tuple|Any|Callable|TypeVar)\\b", code)
    if typing_types:
        unique_types = sorted(set(typing_types))
        imports.add(f"from typing import {', '.join(unique_types)}")
    if re.search("field\\(", code):
        imports.add("from dataclasses import field")
    if re.search("auto\\(\\)", code):
        imports.add("from enum import auto")
    return imports


def merge_imports(existing_imports: list[str], needed_imports: set[str]) -> list[str]:
    all_imports = set(existing_imports)
    for imp in needed_imports:
        all_imports.add(imp)

    def import_key(imp: str) -> tuple[int, str]:
        if imp.startswith("from "):
            module = imp.split()[1].split(".")[0]
        elif imp.startswith("import "):
            module = imp.split()[1].split(".")[0]
        else:
            module = imp
        stdlib_modules = {
            "typing",
            "dataclasses",
            "enum",
            "abc",
            "pathlib",
            "datetime",
            "collections",
            "itertools",
            "functools",
            "re",
            "json",
            "logging",
            "os",
            "sys",
            "math",
            "random",
        }
        is_stdlib = module in stdlib_modules
        return (0 if is_stdlib else 1, imp)

    return sorted(all_imports, key=import_key)


def enhance_entity_code(entity: dict[str, Any]) -> str:
    code = entity["code"]
    if entity.get("is_constant"):
        return f"# Extracted from: {entity['path']}\n# Constant: {entity['full_name']}\n\n{code}"
    needed_imports = analyze_dependencies(code)
    existing_imports = entity.get("imports", [])
    if entity.get("imports_from"):
        for module, names in entity["imports_from"].items():
            if names:
                existing_imports.append(f"from {module} import {', '.join(sorted(names))}")
    all_imports = merge_imports(existing_imports, needed_imports)
    header = f"# Extracted from: {entity['path']}\n"
    if all_imports:
        imports_section = "\n".join(all_imports) + "\n\n"
        return header + imports_section + code
    return header + code


def save_entity(entity: dict[str, Any]) -> Path | None:
    filename_base = f"{entity['full_name']}.py"
    output_path_base = OUTPUT_DIR / entity["type"] / filename_base.lower()
    output_path_base.parent.mkdir(parents=True, exist_ok=True)
    enhanced_code = enhance_entity_code(entity)
    final_py_path = unique_path(output_path_base)
    try:
        final_py_path.write_text(enhanced_code, encoding="utf-8")
        return final_py_path
    except Exception as e:
        print(f"Error saving {final_py_path}: {e}")
        return None


def extract_entities_from_content(content: str, path: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(content)
        extractor = EntityExtractor(content, path)
        extractor.visit(tree)
        return extractor.entities
    except SyntaxError:
        return []
    except Exception as e:
        print(f"Error parsing AST for {path}: {e}")
        return []


def is_python_file_no_extension(path: Path) -> bool:
    if path.suffix:
        return False
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            first_lines = "".join(f.readlines(1024))
            if re.match("#!\\s*/.*python", first_lines):
                return True
            if any(keyword in first_lines for keyword in ["def ", "class ", "import ", "from "]):
                return True
    except:
        pass
    return False


def process_single_file(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    entities = []
    imports = []
    try:
        if path.suffix == ".py" or is_python_file_no_extension(path):
            content = path.read_text(encoding="utf-8", errors="ignore")
            entities = extract_entities_from_content(content, path)
            imports = ImportCollector.collect_from_file(path)
        return (entities, imports)
    except Exception as e:
        print(f"Error reading file {path}: {e}")
        return ([], [])


def process_archive(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    entities = []
    all_imports = []
    if path.suffix == ".zst":
        if HAS_ZSTD:
            try:
                dctx = zstd.ZstdDecompressor()
                content = dctx.decompress(path.read_bytes()).decode("utf-8", errors="ignore")
                entities = extract_entities_from_content(content, path)
                imports = ImportCollector.parse_imports_with_ast(content)
                return (entities, imports)
            except Exception as e:
                print(f"Error decompressing ZST file {path}: {e}")
        else:
            print(f"Warning: zstd module not available, skipping {path}")
        return ([], [])
    if path.suffix in {".zip", ".whl"}:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for member in zf.namelist():
                    member_path = Path(member)
                    if member_path.suffix == ".py":
                        with zf.open(member) as member_file:
                            content = member_file.read().decode("utf-8", errors="ignore")
                            virtual_path = Path(f"{path}/{member}")
                            entities.extend(extract_entities_from_content(content, virtual_path))
                            all_imports.extend(ImportCollector.parse_imports_with_ast(content))
        except Exception as e:
            print(f"Error processing ZIP/WHL archive {path}: {e}")
    elif any(path.name.endswith(ext) for ext in [".tar", ".tar.gz", ".tgz", ".tar.zst", ".tar.xz"]):
        mode_map = {
            ".tar.gz": "r:gz",
            ".tgz": "r:gz",
            ".tar.zst": "r:zst",
            ".tar.xz": "r:xz",
            ".tar": "r",
        }
        mode = next((mode_map[ext] for ext in mode_map if path.name.endswith(ext)), "r")
        try:
            with tarfile.open(path, mode) as tf:
                for member in tf.getmembers():
                    member_path = Path(member.name)
                    if member.isfile() and member_path.suffix == ".py":
                        member_file = tf.extractfile(member)
                        if member_file:
                            content = member_file.read().decode("utf-8", errors="ignore")
                            virtual_path = Path(f"{path}/{member.name}")
                            entities.extend(extract_entities_from_content(content, virtual_path))
                            all_imports.extend(ImportCollector.parse_imports_with_ast(content))
        except tarfile.ReadError:
            pass
        except Exception as e:
            print(f"Error processing TAR archive {path}: {e}")
    return (entities, all_imports)


def worker_process(path_str: str) -> tuple[list[dict[str, Any]], list[str]]:
    path = Path(path_str)
    if path.name.endswith(ARCHIVE_EXTENSIONS):
        return process_archive(path)
    return process_single_file(path)


def save_global_imports(all_imports: list[str], source_dir: Path) -> Path | None:
    if not all_imports:
        return None
    unique_imports = sorted(set(all_imports))
    filtered_imports = [imp for imp in unique_imports if not imp.startswith("from .")]
    outfile = OUTPUT_DIR / f"{source_dir.name}_imports.py"
    if outfile.exists():
        outfile = unique_path(outfile)
    outfile.write_text("\n".join(filtered_imports), encoding="utf-8")
    return outfile


def process_files_parallel(
    file_paths: list[str], max_workers: int | None = 8
) -> tuple[list[dict[str, Any]], list[str]]:
    all_entities = []
    all_imports = []
    if max_workers is None:
        import os

        max_workers = min(os.cpu_count() or 4, 8)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_path = {executor.submit(worker_process, path): path for path in file_paths}
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                entities, imports = future.result()
                all_entities.extend(entities)
                all_imports.extend(imports)
                print(f"✓ Processed: {path} ({len(entities)} entities, {len(imports)} imports)")
            except Exception as e:
                print(f"✗ Failed: {path} - {e}")
    return (all_entities, all_imports)


def print_statistics(entities: list[dict[str, Any]], imports: list[str], saved_entities: int) -> None:
    print("\n" + "=" * 35)
    print("PROCESSING STATISTICS")
    print("=" * 35)
    entity_types = {}
    for entity in entities:
        etype = entity["type"]
        entity_types[etype] = entity_types.get(etype, 0) + 1
    for etype, count in sorted(entity_types.items()):
        print(f"  • {etype.capitalize()}s: {count}")
    import_modules = Counter()
    for imp in imports:
        if imp.startswith("import "):
            module = imp.split()[1].split(".")[0]
            import_modules[module] += 1
        elif imp.startswith("from "):
            module = imp.split()[1].split(".")[0]
            import_modules[module] += 1
    if import_modules:
        print("\n📖 Most Common Imports:")
        for module, count in import_modules.most_common(10):
            print(f"  • {module}: {count} times")
    print(f"\n💾 Saved Entities: {saved_entities}")


def main() -> int:
    cwd = Path.cwd()
    files = get_files(cwd)
    files_to_process = []
    print("\n🔎 Finding Python files and archives...")
    for path in files:
        if path.is_relative_to(OUTPUT_DIR):
            continue
        is_archive = any(path.name.endswith(ext) for ext in ARCHIVE_EXTENSIONS)
        is_py = path.suffix in ALLOWED_PYTHON_EXTENSIONS or is_python_file_no_extension(path)
        if is_archive or is_py:
            files_to_process.append(str(path))
    if not files_to_process:
        print("❌ No Python files or archives found to process.")
        return 1
    print(f"Found {len(files_to_process)} files to process.")
    all_entities, all_imports = process_files_parallel(files_to_process)
    if not all_entities and (not all_imports):
        print("❌ No entities or imports extracted.")
        return 1
    saved_count = 0
    for idx, entity in enumerate(all_entities, 1):
        if save_entity(entity):
            saved_count += 1
        if idx % 100 == 0:
            print(f"  Progress: {idx}/{len(all_entities)} entities processed")
    if all_imports:
        imports_file = save_global_imports(all_imports, cwd)
        if imports_file:
            print(f"✓ Imports saved to: {imports_file}")
    print_statistics(all_entities, all_imports, saved_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
