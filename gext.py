which script is better, merge them as one, add functionality that specific in one script as cli arg
return full annotated code
# script 1
import ast
import os
import re
import sys
import tarfile
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from loguru import logger

try:
    import zstd

    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".venv", "node_modules", ".env", ".pytest_cache"}
)
COMMON_IMPORTS: dict[str, set[str]] = {
    "typing": {
        "List",
        "Dict",
        "Set",
        "Tuple",
        "Optional",
        "Union",
        "Any",
        "Callable",
        "Type",
        "Generic",
        "TypeVar",
        "cast",
        "overload",
        "Protocol",
        "Iterator",
        "Iterable",
        "Sequence",
        "Mapping",
    },
    "dataclasses": {
        "dataclass",
        "field",
        "InitVar",
        "FrozenInstanceError",
        "MISSING",
        "fields",
        "asdict",
        "astuple",
        "make_dataclass",
        "replace",
    },
    "functools": {
        "lru_cache",
        "wraps",
        "partial",
        "total_ordering",
        "reduce",
        "cmp_to_key",
        "singledispatch",
    },
    "itertools": {
        "combinations",
        "permutations",
        "product",
        "chain",
        "groupby",
        "repeat",
        "cycle",
        "islice",
        "takewhile",
        "dropwhile",
    },
    "pathlib": {
        "Path",
        "PurePath",
        "PureWindowsPath",
        "PurePosixPath",
        "WindowsPath",
        "PosixPath",
    },
    "datetime": {
        "datetime",
        "date",
        "time",
        "timedelta",
        "timezone",
        "tzinfo",
        "strptime",
        "now",
    },
    "json": {"dumps", "loads", "dump", "load", "JSONEncoder", "JSONDecoder"},
    "re": {
        "compile",
        "match",
        "search",
        "findall",
        "finditer",
        "sub",
        "split",
        "escape",
        "IGNORECASE",
        "MULTILINE",
        "DOTALL",
    },
    "collections": {
        "defaultdict",
        "OrderedDict",
        "Counter",
        "deque",
        "namedtuple",
        "ChainMap",
    },
    "enum": {"Enum", "IntEnum", "Flag", "IntFlag", "auto", "unique"},
    "abc": {
        "ABC",
        "abstractmethod",
        "abstractproperty",
        "ABCMeta",
        "abstractclassmethod",
    },
    "contextlib": {
        "contextmanager",
        "closing",
        "suppress",
        "redirect_stdout",
        "redirect_stderr",
    },
    "copy": {"copy", "deepcopy"},
    "pickle": {"dumps", "loads", "dump", "load"},
    "logging": {
        "getLogger",
        "debug",
        "info",
        "warning",
        "error",
        "critical",
        "basicConfig",
    },
    "os": {
        "path",
        "environ",
        "getcwd",
        "chdir",
        "listdir",
        "mkdir",
        "makedirs",
        "remove",
        "rmdir",
    },
    "sys": {"argv", "exit", "stdout", "stderr", "stdin", "path", "modules"},
    "subprocess": {"run", "Popen", "PIPE", "STDOUT", "CalledProcessError"},
    "threading": {"Thread", "Lock", "RLock", "Condition", "Semaphore", "Event"},
    "asyncio": {"run", "gather", "create_task", "sleep", "Queue", "Event", "Lock"},
    "urllib": {"request", "parse", "error"},
    "requests": {"get", "post", "put", "delete", "Session", "Response"},
    "numpy": {"array", "zeros", "ones", "arange", "linspace", "ndarray"},
    "pandas": {"DataFrame", "Series", "read_csv", "read_excel", "concat", "merge"},
}


@dataclass
class Entity:

    name: str
    type: str
    source: str
    full_name: str
    source_file: str
    line_number: int
    imports: set[str] = field(default_factory=set)
    decorators: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:

    path: str
    entities: list[Entity] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    imports: set[str] = field(default_factory=set)


class CodeValidator:

    @staticmethod
    def validate_python_code(source: str) -> tuple[bool, str | None]:
        try:
            tree = ast.parse(source)

            compile(source, "<validation>", "exec")

            undefined_names = CodeValidator._find_undefined_names(tree)
            if undefined_names:
                builtins = (
                    set(dir(__builtins__))
                    if isinstance(__builtins__, dict)
                    else set(dir(__builtins__))
                )
                common_names = {
                    "self",
                    "cls",
                    "List",
                    "Dict",
                    "Set",
                    "Tuple",
                    "Optional",
                    "Union",
                    "Any",
                    "Callable",
                    "Type",
                    "Generic",
                    "TypeVar",
                    "Path",
                    "datetime",
                    "date",
                    "time",
                    "timedelta",
                    "timezone",
                    "json",
                    "re",
                    "os",
                    "sys",
                    "logging",
                    "logger",
                    "loguru",
                }
                truly_undefined = undefined_names - builtins - common_names
                if truly_undefined:
                    logger.debug(f"Potential undefined names: {truly_undefined}")

            return (True, None)
        except SyntaxError as e:
            return (False, f"Syntax error: {e}")
        except Exception as e:
            return (False, f"Validation error: {e}")

    @staticmethod
    def _find_undefined_names(tree: ast.AST) -> set[str]:
        undefined = set()
        defined = set()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    undefined.add(node.id)
                elif isinstance(node.ctx, ast.Store):
                    defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split(".")[0]
                    defined.add(name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    if name != "*":
                        defined.add(name)

        return undefined - defined


class MethodConverter:

    @staticmethod
    def method_to_function(source: str) -> str:
        try:
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.args.args and node.args.args[0].arg == "self":
                        node.args.args.pop(0)
                        if (
                            node.args.posonlyargs
                            and node.args.posonlyargs[0].arg == "self"
                        ):
                            node.args.posonlyargs.pop(0)

                    MethodConverter._remove_self_references(node)

                    node.decorator_list = [
                        d
                        for d in node.decorator_list
                        if not MethodConverter._is_class_decorator(d)
                    ]

                    return ast.unparse(node)

            return source
        except Exception as e:
            logger.warning(f"Failed to convert method to function: {e}")
            return source

    @staticmethod
    def _remove_self_references(node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name) and child.value.id == "self":
                    child.value = ast.Name(id=child.attr, ctx=ast.Load())
                    child.attr = ""
            elif isinstance(child, ast.Name) and child.id == "self":
                child.id = "self_removed"

    @staticmethod
    def _is_class_decorator(decorator: ast.expr) -> bool:
        if isinstance(decorator, ast.Name):
            return decorator.id in {
                "staticmethod",
                "classmethod",
                "property",
                "abstractmethod",
            }
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr in {
                "staticmethod",
                "classmethod",
                "property",
                "abstractmethod",
            }
        return False


class ImportAnalyzer:

    @staticmethod
    def extract_imports_from_source(source: str) -> set[str]:
        imports: set[str] = set()
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(f"import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = ", ".join(alias.name for alias in node.names)
                    if node.level > 0:
                        module = "." * node.level + module
                    imports.add(f"from {module} import {names}")
        except SyntaxError:
            pass
        return imports

    @staticmethod
    def detect_needed_imports(source: str) -> set[str]:
        needed: set[str] = set()
        for module, symbols in COMMON_IMPORTS.items():
            for symbol in symbols:
                if re.search(f"\\b{re.escape(symbol)}\\b", source):
                    if module == "typing":
                        needed.add(f"from typing import {symbol}")
                    elif module == "dataclasses":
                        needed.add(f"from dataclasses import {symbol}")
                    elif module == "abc":
                        needed.add(f"from abc import {symbol}")
                    elif module == "functools":
                        needed.add(f"from functools import {symbol}")
                    elif module == "enum":
                        needed.add(f"from enum import {symbol}")
                    else:
                        needed.add(f"from {module} import {symbol}")
        if "Path(" in source or "PurePath(" in source:
            needed.add("from pathlib import Path")
        if "datetime(" in source or "date(" in source:
            needed.add("from datetime import datetime, date")
        if "logging.getLogger" in source or "logger =" in source:
            needed.add("import logging")
        return needed

    @staticmethod
    def consolidate_imports(existing: set[str], needed: set[str]) -> list[str]:
        all_imports = existing | needed
        organized: list[str] = []
        stdlib_imports: list[str] = []
        thirdparty_imports: list[str] = []
        local_imports: list[str] = []

        for imp in sorted(all_imports):
            if imp.startswith(("from .", "import .")):
                local_imports.append(imp)
            elif imp.startswith(("from typing", "import typing")):
                stdlib_imports.insert(0, imp)
            elif any(
                imp.startswith((f"from {mod}", f"import {mod}"))
                for mod in [
                    "os",
                    "sys",
                    "json",
                    "re",
                    "pathlib",
                    "datetime",
                    "asyncio",
                    "subprocess",
                    "threading",
                    "logging",
                ]
            ):
                stdlib_imports.append(imp)
            else:
                thirdparty_imports.append(imp)

        organized.extend(sorted(stdlib_imports))
        if thirdparty_imports:
            organized.extend([""] + sorted(thirdparty_imports))
        if local_imports:
            organized.extend([""] + sorted(local_imports))
        return [imp for imp in organized if imp]


class EntityVisitor(ast.NodeVisitor):

    def __init__(self, source_lines: list[str], path: str):
        self.source_lines = source_lines
        self.path = path
        self.entities: list[Entity] = []
        self.current_class: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node, is_async=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node, is_async=True)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        source = self._get_source_slice(node)
        self.entities.append(
            Entity(
                name=node.name,
                type="class",
                source=source,
                full_name=node.name,
                source_file=self.path,
                line_number=node.lineno,
                decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            )
        )
        old_class = self.current_class
        self.current_class = node.name
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._process_function(
                    item, is_async=isinstance(item, ast.AsyncFunctionDef), in_class=True
                )
            self.visit(item)
        self.current_class = old_class

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.current_class is None:
            for target in node.targets:
                if isinstance(target, ast.Name) and self._is_constant_name(target.id):
                    source = self._get_source_slice(node)
                    self.entities.append(
                        Entity(
                            name=target.id,
                            type="constant",
                            source=source,
                            full_name=target.id,
                            source_file=self.path,
                            line_number=node.lineno,
                        )
                    )
        self.generic_visit(node)

    def _process_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        is_async: bool = False,
        in_class: bool = False,
    ) -> None:
        source = self._get_source_slice(node)

        if in_class:
            entity_type = "function"
            source = MethodConverter.method_to_function(source)
            full_name = (
                f"{self.current_class}_{node.name}" if self.current_class else node.name
            )
        else:
            entity_type = "function"
            full_name = node.name

        self.entities.append(
            Entity(
                name=node.name,
                type=entity_type,
                source=source,
                full_name=full_name,
                source_file=self.path,
                line_number=node.lineno,
                decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            )
        )

    def _get_source_slice(self, node: ast.stmt) -> str:
        if not self.source_lines:
            return ""
        start_line = node.lineno - 1
        end_line = node.end_lineno or node.lineno
        start_line = max(0, start_line)
        end_line = min(len(self.source_lines), end_line)
        lines = self.source_lines[start_line:end_line]
        return "".join(lines)

    @staticmethod
    def _get_decorator_name(decorator: ast.expr) -> str:
        if isinstance(decorator, ast.Name):
            return decorator.id
        elif isinstance(decorator, ast.Attribute):
            return decorator.attr
        return ""

    @staticmethod
    def _is_constant_name(name: str) -> bool:
        return bool(re.match("^[A-Z_][A-Z0-9_]*$", name))


def is_python_file(path: Path) -> bool:
    if path.suffix == ".py":
        return True
    try:
        with open(path, "rb") as f:
            first_line = f.readline()
            if first_line.startswith(b"#!"):
                return b"python" in first_line
    except OSError:
        pass
    return False


def extract_from_file(path: Path) -> ExtractionResult:
    result = ExtractionResult(str(path))
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            result.errors.append(f"Syntax error: {e}")
            return result
        result.imports = ImportAnalyzer.extract_imports_from_source(source)
        source_lines = source.split("\n")
        visitor = EntityVisitor(source_lines, str(path))
        visitor.visit(tree)
        result.entities = visitor.entities
    except Exception as e:
        result.errors.append(f"Error processing file: {e}")
    return result


def extract_from_archive(
    archive_path: Path, archive_type: str
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    if archive_type in {".zip", ".whl"}:
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith(".py"):
                        try:
                            content = zf.read(member).decode("utf-8", errors="ignore")
                            virtual_path = f"{archive_path.name}::{member}"
                            results.append((virtual_path, content))
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Failed to extract from zip archive {archive_path}: {e}")
    elif archive_type in {".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar"}:
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                for member in tf.getmembers():
                    if member.name.endswith(".py") and member.isfile():
                        try:
                            f = tf.extractfile(member)
                            if f:
                                content = f.read().decode("utf-8", errors="ignore")
                                virtual_path = f"{archive_path.name}::{member.name}"
                                results.append((virtual_path, content))
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"Failed to extract from tar archive {archive_path}: {e}")
    elif archive_type == ".tar.zst":
        if not HAS_ZSTD:
            logger.warning("zstandard library not available for .tar.zst archives")
            return results
        try:
            with open(archive_path, "rb") as f:
                dctx = zstd.ZstdDecompressor()
                with (
                    dctx.stream_reader(f) as reader,
                    tarfile.open(fileobj=reader, mode="r|") as tf,
                ):
                    for member in tf:
                        if member.name.endswith(".py") and member.isfile():
                            try:
                                f_obj = tf.extractfile(member)
                                if f_obj:
                                    content = f_obj.read().decode(
                                        "utf-8", errors="ignore"
                                    )
                                    virtual_path = f"{archive_path.name}::{member.name}"
                                    results.append((virtual_path, content))
                            except Exception:
                                pass
        except Exception as e:
            logger.warning(
                f"Failed to extract from tar.zst archive {archive_path}: {e}"
            )
    return results


def extract_from_archive_member(virtual_path: str, source: str) -> ExtractionResult:
    result = ExtractionResult(virtual_path)
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        result.errors.append(f"Syntax error: {e}")
        return result
    result.imports = ImportAnalyzer.extract_imports_from_source(source)
    source_lines = source.split("\n")
    visitor = EntityVisitor(source_lines, virtual_path)
    visitor.visit(tree)
    result.entities = visitor.entities
    return result


def process_file_worker(path: Path) -> ExtractionResult:
    return extract_from_file(path)


def process_archive_member_worker(args: tuple[str, str]) -> ExtractionResult:
    virtual_path, source = args
    return extract_from_archive_member(virtual_path, source)


def scan_directory(directory: str) -> tuple[list[Path], list[tuple[str, str]]]:
    base_dir = Path(directory).resolve()
    python_files: list[Path] = []
    archive_members: list[tuple[str, str]] = []

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        root_path = Path(root)
        for filename in files:
            path = root_path / filename
            if path.is_symlink():
                continue
            if is_python_file(path):
                python_files.append(path)
            elif path.suffix in {".zip", ".whl"}:
                members = extract_from_archive(path, path.suffix)
                archive_members.extend(members)
            elif path.suffix in {".gz", ".bz2", ".xz", ".zst"}:
                name = path.name
                if name.endswith((".tar.gz", ".tgz")):
                    archive_type = ".tar.gz"
                elif name.endswith(".tar.bz2"):
                    archive_type = ".tar.bz2"
                elif name.endswith(".tar.xz"):
                    archive_type = ".tar.xz"
                elif name.endswith(".tar.zst"):
                    archive_type = ".tar.zst"
                else:
                    continue
                members = extract_from_archive(path, archive_type)
                archive_members.extend(members)
            elif path.suffix == ".tar":
                members = extract_from_archive(path, ".tar")
                archive_members.extend(members)
    return (python_files, archive_members)


def write_entity(output_dir: Path, entity: Entity) -> Path | None:
    entity_dir = output_dir / entity.type
    entity_dir.mkdir(parents=True, exist_ok=True)
    base_filename = entity.full_name.replace("::", "_").replace("/", "_")
    filename = f"{base_filename}.py"
    path = entity_dir / filename
    counter = 1
    while path.exists():
        counter += 1
        path = entity_dir / f"{base_filename}_{counter}.py"

    existing_imports = ImportAnalyzer.extract_imports_from_source(entity.source)
    needed_imports = ImportAnalyzer.detect_needed_imports(entity.source)
    imports = ImportAnalyzer.consolidate_imports(existing_imports, needed_imports)

    lines: list[str] = []
    lines.append(f"# Extracted from: {entity.source_file}:{entity.line_number}\n")
    if imports:
        lines.extend([imp + "\n" for imp in imports])
        lines.append("\n")
    lines.append(entity.source)
    if not entity.source.endswith("\n"):
        lines.append("\n")

    complete_code = "".join(lines)
    is_valid, error_msg = CodeValidator.validate_python_code(complete_code)

    if not is_valid:
        logger.warning(f"Skipping invalid entity {entity.full_name}: {error_msg}")
        return None

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(complete_code)
        return path
    except Exception as e:
        logger.error(f"Error writing entity: {e}")
        return None


def write_imports_file(output_dir: Path, all_imports: set[str]) -> None:
    organized = ImportAnalyzer.consolidate_imports(all_imports, set())
    path = output_dir / "imports.py"
    content = "# Aggregated imports from extracted entities\n\n" + "".join(
        imp + "\n" for imp in organized
    )

    is_valid, error_msg = CodeValidator.validate_python_code(content)
    if is_valid:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        logger.warning(f"Failed to write imports file: {error_msg}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Python code entities from files and archives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\nExamples:\n\n  python extract_entities.py\n\n\n  python extract_entities.py -t\n\n\n  python extract_entities.py --workers 16\n        ",
    )
    parser.add_argument(
        "-t",
        "--temp",
        action="store_true",
        help="Save to ~/tmp/output/ instead of ./output/",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of worker processes",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to scan (default: current directory)",
    )
    args = parser.parse_args()

    if args.temp:
        output_dir = Path.home() / "tmp" / "output"
    else:
        output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning directory: {Path(args.directory).resolve()}")
    print(f"Output directory: {output_dir.resolve()}\n")

    python_files, archive_members = scan_directory(args.directory)
    print(
        f"Found {len(python_files):,} Python files and {len(archive_members):,} archive members\n"
    )

    all_entities: list[Entity] = []
    all_imports: set[str] = set()
    entity_count: dict[str, int] = {"function": 0, "class": 0, "constant": 0}
    error_count = 0

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures: dict = {
            executor.submit(process_file_worker, fpath): ("file", str(fpath))
            for fpath in python_files
        }
        for virtual_path, source in archive_members:
            futures[
                executor.submit(process_archive_member_worker, (virtual_path, source))
            ] = (
                "archive",
                virtual_path,
            )

        processed = 0
        for future in as_completed(futures):
            _source_type, source_path = futures[future]
            processed += 1
            try:
                result = future.result()
                all_entities.extend(result.entities)
                all_imports.update(result.imports)
                for entity in result.entities:
                    entity_count[entity.type] += 1
                if result.errors:
                    error_count += len(result.errors)
                    for error in result.errors:
                        logger.error(f"Error in {source_path}: {error}")
                if processed % 50 == 0:
                    logger.debug(f"Processed: {processed}/{len(futures)}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing {source_path}: {e}")

    print(f"\nExtracted {len(all_entities):,} entities:")
    for etype, count in entity_count.items():
        if count > 0:
            print(f"  {etype}: {count}")

    print("\nValidating and writing entities to output directory...")
    written_count = 0
    skipped_count = 0
    for entity in all_entities:
        result = write_entity(output_dir, entity)
        if result:
            written_count += 1
        else:
            skipped_count += 1

    print(f"Saved {written_count}/{len(all_entities)} entities")
    if skipped_count > 0:
        logger.warning(f"Skipped {skipped_count} invalid entities")
    print()

    write_imports_file(output_dir, all_imports)
    print("Saved aggregated imports to imports.py")
    print(f"\nTotal unique imports: {len(all_imports)}")

    if error_count > 0:
        logger.warning(f"Errors encountered: {error_count}")
    return 0


if __name__ == "__main__":
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )
    raise SystemExit(main())


# script 2

import ast
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from pathlib import Path

from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class Entity:
    name: str
    path: str
    line_number: int


@dataclass
class ExtractionResult:
    path: Path
    classes: list[Entity]
    functions: list[Entity]
    constants: list[Entity]
    imports: set[str]


class EntityExtractor(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.classes: list[Entity] = []
        self.functions: list[Entity] = []
        self.constants: list[Entity] = []
        self.imports: set[str] = set()
        self._in_class = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(
            Entity(name=node.name, path=str(self.path), line_number=node.lineno)
        )
        old_in_class = self._in_class
        self._in_class = True
        self.generic_visit(node)
        self._in_class = old_in_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not self._in_class:
            self.functions.append(
                Entity(
                    name=node.name,
                    path=str(self.path),
                    line_number=node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if not self._in_class:
            self.functions.append(
                Entity(
                    name=node.name,
                    path=str(self.path),
                    line_number=node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._in_class:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    self.constants.append(
                        Entity(
                            name=target.id,
                            path=str(self.path),
                            line_number=node.lineno,
                        )
                    )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.add(f"import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.add(f"from {module} import {alias.name}")
        self.generic_visit(node)


def extract_from_file(path: Path) -> ExtractionResult:
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        extractor = EntityExtractor(path)
        extractor.visit(tree)
        return ExtractionResult(
            path=path,
            classes=extractor.classes,
            functions=extractor.functions,
            constants=extractor.constants,
            imports=extractor.imports,
        )
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to parse {path}: {e}")
        return ExtractionResult(
            path=path, classes=[], functions=[], constants=[], imports=set()
        )


def find_python_files(root_dir: Path) -> list[Path]:
    return list(root_dir.rglob("*.py"))


def save_entities(
    output_dir: Path,
    entity_type: str,
    entities_by_file: dict[str, list[Entity]],
    unique_entities: set[str],
) -> None:
    entity_dir = output_dir / entity_type
    entity_dir.mkdir(parents=True, exist_ok=True)
    for path, entities in entities_by_file.items():
        if entities:
            file_name = Path(path).stem + ".txt"
            output_file = entity_dir / file_name
            with open(output_file, "w", encoding="utf-8") as f:
                f.writelines(
                    f"{entity.name} (line {entity.line_number})\n"
                    for entity in sorted(entities, key=lambda e: e.name)
                )
    unique_file = entity_dir / "unique.txt"
    with open(unique_file, "w", encoding="utf-8") as f:
        f.writelines(f"{name}\n" for name in sorted(unique_entities))
    print(f"Saved {len(unique_entities)} unique {entity_type}")


def save_imports(output_dir: Path, imports_by_dir: dict[str, set[str]]) -> None:
    imports_dir = output_dir / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    for dir_name, imports in imports_by_dir.items():
        if imports:
            file_name = f"imports-{dir_name}.txt"
            output_file = imports_dir / file_name
            with open(output_file, "w", encoding="utf-8") as f:
                f.writelines(f"{imp}\n" for imp in sorted(imports))
    print(f"Saved imports for {len(imports_by_dir)} directories")


def main(
    root_dir: str = ".", output_dir: str = "output", num_workers: int | None = None
) -> None:
    root_path = Path(root_dir)
    output_path = Path(output_dir)
    if not root_path.exists():
        logger.error(f"Root directory not found: {root_path}")
        sys.exit(1)
    print(f"Scanning for Python files in {root_path}...")
    py_files = find_python_files(root_path)
    if not py_files:
        logger.warning("No Python files found.")
        return
    print(f"Found {len(py_files)} Python files")
    num_workers = num_workers or cpu_count()
    print(f"Using {num_workers} workers for parallel processing")
    entities_by_file = defaultdict(list)
    unique_classes = set()
    unique_functions = set()
    unique_constants = set()
    imports_by_dir = defaultdict(set)
    with Pool(num_workers) as pool:
        results = list(
            tqdm(
                pool.imap_unordered(extract_from_file, py_files),
                total=len(py_files),
                desc="Extracting entities",
                unit="file",
            )
        )
    print("Aggregating results...")
    for result in results:
        for entity in result.classes:
            entities_by_file["classes"][result.path].append(entity)
            unique_classes.add(entity.name)
        for entity in result.functions:
            entities_by_file["functions"][result.path].append(entity)
            unique_functions.add(entity.name)
        for entity in result.constants:
            entities_by_file["constants"][result.path].append(entity)
            unique_constants.add(entity.name)
        dir_name = result.path.parent.name or "root"
        imports_by_dir[dir_name].update(result.imports)
    entities_by_file = {key: dict(val) for key, val in entities_by_file.items()}
    print(f"Saving results to {output_path}...")
    output_path.mkdir(parents=True, exist_ok=True)
    save_entities(
        output_path, "class", entities_by_file.get("classes", {}), unique_classes
    )
    save_entities(
        output_path, "func", entities_by_file.get("functions", {}), unique_functions
    )
    save_entities(
        output_path, "const", entities_by_file.get("constants", {}), unique_constants
    )
    save_imports(output_path, imports_by_dir)
    print("=" * 40)
    print("Extraction Summary:")
    print(f"  Files processed: {len(py_files)}")
    print(f"  Unique classes: {len(unique_classes)}")
    print(f"  Unique functions: {len(unique_functions)}")
    print(f"  Unique constants: {len(unique_constants)}")
    print(f"  Total imports: {sum(len(v) for v in imports_by_dir.values())}")
    print("=" * 40)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract entities from Python files recursively"
    )
    parser.add_argument(
        "-r",
        "--root",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o", "--output", default="output", help="Output directory (default: output)"
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        help="Number of parallel workers (default: CPU count)",
    )
    args = parser.parse_args()
    main(args.root, args.output, args.workers)
