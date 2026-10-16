from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import libcst as cst
from libcst import MetadataWrapper
from libcst.metadata import PositionProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Entity:
    name: str
    type: str
    file_path: str
    source_code: str
    line_start: int
    line_end: int
    docstring: str = ""
    parent: str = ""
    imports: list[str] = None
    decorators: list[str] = None


class EntityExtractor(cst.CSTTransformer):
    def __init__(self, file_path: str, source_lines: list[str]):
        self.file_path = file_path
        self.source_lines = source_lines
        self.entities: list[Entity] = []
        self.current_class: str = ""
        self.module_imports: list[str] = []
        self.constants: set[str] = set()
        self.wrapper: MetadataWrapper | None = None

    def set_wrapper(self, wrapper: MetadataWrapper):
        self.wrapper = wrapper

    def _get_node_position(self, node) -> tuple[int, int]:
        if not self.wrapper:
            return (0, 0)
        try:
            position = self.wrapper.resolve(PositionProvider)[node]
            start_line = position.start.line
            end_line = position.end.line
            return (start_line, end_line)
        except (KeyError, AttributeError):
            return (0, 0)

    def _get_source_code(self, node, start_line: int, end_line: int) -> str:
        if start_line > 0 and end_line > 0 and start_line <= len(self.source_lines):
            return "".join(self.source_lines[start_line - 1 : end_line])
        else:
            return cst.Module(body=[cst.SimpleStatementLine(body=[node])]).code

    def visit_Import(self, node: cst.Import) -> bool:
        if not self.current_class:
            import_code = cst.Module(body=[cst.SimpleStatementLine(body=[node])]).code
            if import_code not in self.module_imports:
                self.module_imports.append(import_code)
        return True

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        if not self.current_class:
            import_code = cst.Module(body=[cst.SimpleStatementLine(body=[node])]).code
            if import_code not in self.module_imports:
                self.module_imports.append(import_code)
        return True

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.CSTNode:
        class_name = original_node.name.value
        start_line, end_line = self._get_node_position(original_node)
        source_code = self._get_source_code(original_node, start_line, end_line)
        docstring = self._extract_docstring(original_node)
        decorators = []
        if original_node.decorators:
            for decorator in original_node.decorators:
                decorators.append(cst.Module(body=[cst.SimpleStatementLine(body=[decorator])]).code.strip())
        self.entities.append(
            Entity(
                name=class_name,
                type="class",
                file_path=str(self.file_path),
                source_code=source_code,
                line_start=start_line,
                line_end=end_line,
                docstring=docstring,
                parent=self.current_class,
                imports=self.module_imports.copy() if not self.current_class else [],
                decorators=decorators,
            )
        )
        self.current_class = class_name
        return updated_node

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.CSTNode:
        func_name = original_node.name.value
        start_line, end_line = self._get_node_position(original_node)
        source_code = self._get_source_code(original_node, start_line, end_line)
        docstring = self._extract_docstring(original_node)
        decorators = []
        if original_node.decorators:
            for decorator in original_node.decorators:
                decorators.append(cst.Module(body=[cst.SimpleStatementLine(body=[decorator])]).code.strip())
        self.entities.append(
            Entity(
                name=func_name,
                type="function",
                file_path=str(self.file_path),
                source_code=source_code,
                line_start=start_line,
                line_end=end_line,
                docstring=docstring,
                parent=self.current_class,
                imports=self.module_imports.copy() if not self.current_class else [],
                decorators=decorators,
            )
        )
        return updated_node

    def visit_Assign(self, node: cst.Assign) -> bool:
        if self.current_class:
            return True
        for target in node.targets:
            if isinstance(target.target, cst.Name):
                var_name = target.target.value
                if (var_name.isupper() or var_name == "__all__") and var_name not in self.constants:
                    self.constants.add(var_name)
                    start_line, end_line = self._get_node_position(node)
                    source_code = self._get_source_code(node, start_line, end_line)
                    self.entities.append(
                        Entity(
                            name=var_name,
                            type="constant",
                            file_path=str(self.file_path),
                            source_code=source_code,
                            line_start=start_line,
                            line_end=end_line,
                            docstring="",
                            parent="",
                            imports=self.module_imports.copy(),
                            decorators=[],
                        )
                    )
        return True

    def _extract_docstring(self, node) -> str:
        if not node.body:
            return ""
        first_stmt = node.body[0]
        if isinstance(first_stmt, cst.SimpleStatementLine):
            for stmt in first_stmt.body:
                if isinstance(stmt, cst.Expr) and isinstance(stmt.value, cst.SimpleString):
                    doc = stmt.value.value
                    if (doc.startswith("'''") and doc.endswith("'''")) or (
                        doc.startswith('"""') and doc.endswith('"""')
                    ):
                        doc = doc[3:-3]
                    elif (doc.startswith("'") and doc.endswith("'")) or (doc.startswith('"') and doc.endswith('"')):
                        doc = doc[1:-1]
                    return doc.strip()
        return ""


def process_file(file_path: Path, output_dir: Path) -> dict[str, int]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            source_lines = f.readlines() if hasattr(f, "readlines") else content.splitlines(keepends=True)
        if not source_lines or (len(source_lines) == 1 and source_lines[0] == ""):
            with open(file_path, "r", encoding="utf-8") as f:
                source_lines = f.readlines()
        module = cst.parse_module(content)
        wrapper = MetadataWrapper(module)
        extractor = EntityExtractor(file_path, source_lines)
        extractor.set_wrapper(wrapper)
        wrapper.visit(extractor)
        entities_by_type: dict[str, list[Entity]] = {
            "function": [],
            "class": [],
            "constant": [],
        }
        for entity in extractor.entities:
            if entity.type in entities_by_type:
                entities_by_type[entity.type].append(entity)
        stats = {}
        for entity_type, entities in entities_by_type.items():
            if not entities:
                continue
            type_dir = output_dir / entity_type
            type_dir.mkdir(parents=True, exist_ok=True)
            for entity in entities:
                safe_name = sanitize_filename(entity.name)
                base_filename = f"{safe_name}"
                counter = 1
                py_file_path = type_dir / f"{base_filename}.py"
                while py_file_path.exists():
                    py_file_path = type_dir / f"{base_filename}_{counter}.py"
                    counter += 1
                with open(py_file_path, "w", encoding="utf-8") as f:
                    if entity.imports and not entity.parent:
                        for imp in entity.imports:
                            f.write(imp)
                            if not imp.endswith("\n"):
                                f.write("\n")
                        if entity.imports:
                            f.write("\n")
                    if entity.decorators:
                        for decorator in entity.decorators:
                            f.write(decorator)
                            if not decorator.endswith("\n"):
                                f.write("\n")
                    f.write(entity.source_code)
                metadata_file = type_dir / f"{base_filename}_metadata.json"
                counter_md = 1
                while metadata_file.exists():
                    metadata_file = type_dir / f"{base_filename}_{counter_md}_metadata.json"
                    counter_md += 1
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "entity": {
                                "name": entity.name,
                                "type": entity.type,
                                "file_path": entity.file_path,
                                "line_start": entity.line_start,
                                "line_end": entity.line_end,
                                "docstring": entity.docstring,
                                "parent": entity.parent,
                                "imports": entity.imports,
                                "decorators": entity.decorators,
                            },
                            "extracted_at": datetime.now().isoformat(),
                        },
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
                if entity_type not in stats:
                    stats[entity_type] = 0
                stats[entity_type] += 1
        return stats
    except Exception as e:
        logger.error(f"Error processing {file_path}: {e}")
        import traceback

        traceback.print_exc()
        return {}


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(". ")
    if not name:
        name = "unnamed"
    return name


def get_py_files(paths: list[Path]) -> list[Path]:
    py_files = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            py_files.append(path)
        elif path.is_dir():
            py_files.extend(path.rglob("*.py"))
    return sorted(py_files)


def process_entity_extraction(input_paths: list[Path], output_base: Path, max_workers: int | None = None) -> None:
    py_files = get_py_files(input_paths)
    if not py_files:
        logger.warning("No Python files found to process.")
        return
    logger.info(f"Found {len(py_files)} Python files to process")
    output_base.mkdir(parents=True, exist_ok=True)
    total_stats = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file, py_file, output_base): py_file for py_file in py_files}
        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                stats = future.result()
                if stats:
                    for entity_type, count in stats.items():
                        total_stats[entity_type] = total_stats.get(entity_type, 0) + count
                    logger.info(f"✓ Processed {file_path.name}: {stats}")
                else:
                    logger.info(f"✗ No entities found in {file_path.name}")
            except Exception as e:
                logger.error(f"✗ Failed to process {file_path.name}: {e}")
    logger.info("\n" + "=" * 40)
    logger.info("Extraction Summary:")
    for entity_type, count in sorted(total_stats.items()):
        logger.info(f"  {entity_type}: {count}")
    logger.info("=" * 40)


def main():
    parser = argparse.ArgumentParser(description="Extract entities (functions, classes, constants) from Python files.")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument("-o", "--output", default="output", help="Output directory (default: output)")
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of parallel workers (default: CPU count)",
    )
    args = parser.parse_args()
    if args.paths:
        input_paths = [Path(p).resolve() for p in args.paths]
    else:
        input_paths = [Path.cwd()]
    valid_paths = []
    for path in input_paths:
        if path.exists():
            valid_paths.append(path)
        else:
            logger.warning(f"Path does not exist: {path}")
    if not valid_paths:
        logger.error("No valid input paths provided.")
        sys.exit(1)
    output_dir = Path(args.output).resolve()
    process_entity_extraction(valid_paths, output_dir, args.jobs)


if __name__ == "__main__":
    raise SystemExit(main())
