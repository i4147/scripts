import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path
import libcst as cst
from libcst import MetadataWrapper
from libcst.metadata import PositionProvider
from loguru import logger

WORKER_COUNT = 8
DEFAULT_OUTPUT_DIR = "output"


@dataclass
class Entity:
    docstring = ""
    parent = ""
    imports = field(default_factory=list)
    decorators = field(default_factory=list)


class EntityExtractor(cst.CSTTransformer):
    def __init__(self, path, source_lines):
        self.path = path
        self.source_lines = source_lines
        self.entities = []
        self.current_class = ""
        self.module_imports = []
        self.constants = set()
        self.wrapper = None

    def set_wrapper(self, wrapper):
        self.wrapper = wrapper

    def _get_node_position(self, node):
        if self.wrapper is None:
            return (0, 0)
        try:
            position = self.wrapper.resolve(PositionProvider)[node]
            return (position.start.line, position.end.line)
        except (KeyError, AttributeError):
            return (0, 0)

    def _get_source_code(self, node, start_line, end_line):
        if start_line > 0 and end_line > 0 and start_line <= len(self.source_lines):
            return "".join(self.source_lines[start_line - 1 : end_line])
        module = cst.Module(body=[cst.SimpleStatementLine(body=[node])])
        return module.code

    def visit_Import(self, node):
        if not self.current_class:
            import_code = cst.Module(body=[cst.SimpleStatementLine(body=[node])]).code
            if import_code not in self.module_imports:
                self.module_imports.append(import_code)
        return True

    def visit_ImportFrom(self, node):
        if not self.current_class:
            import_code = cst.Module(body=[cst.SimpleStatementLine(body=[node])]).code
            if import_code not in self.module_imports:
                self.module_imports.append(import_code)
        return True

    def leave_ClassDef(self, original_node, updated_node):
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
                path=str(self.path),
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

    def leave_FunctionDef(self, original_node, updated_node):
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
                path=str(self.path),
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

    def visit_Assign(self, node):
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
                            path=str(self.path),
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

    def _extract_docstring(self, node):
        body = getattr(node, "body", None)
        if body is None:
            return ""
        if not isinstance(body, cst.IndentedBlock):
            return ""
        if not body.body:
            return ""
        first_stmt = body.body[0]
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


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(". ")
    if not name:
        name = "unnamed"
    return name


def process_file(args):
    path, output_dir = args
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        source_lines = content.splitlines(keepends=True)
        module = cst.parse_module(content)
        wrapper = MetadataWrapper(module)
        extractor = EntityExtractor(str(path), source_lines)
        extractor.set_wrapper(wrapper)
        wrapper.visit(extractor)
        entities_by_type = {
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
                py_path = type_dir / f"{base_filename}.py"
                while py_path.exists():
                    py_path = type_dir / f"{base_filename}_{counter}.py"
                    counter += 1
                with open(py_path, "w", encoding="utf-8") as f:
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
                                "path": entity.path,
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
                stats[entity_type] = stats.get(entity_type, 0) + 1
        return stats
    except Exception as e:
        logger.error(f"Error processing {path}: {e}")
        import traceback

        traceback.print_exc()
        return {}


def get_py_files(paths):
    py_files = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            py_files.append(path)
        elif path.is_dir():
            py_files.extend(path.rglob("*.py"))
    return sorted(py_files)


def process_entity_extraction(input_paths, output_base):
    py_files = get_py_files(input_paths)
    if not py_files:
        logger.warning("No Python files found to process.")
        return
    print(f"Found {len(py_files)} Python files to process")
    output_base.mkdir(parents=True, exist_ok=True)
    total_stats = {}
    tasks = [(p, output_base) for p in py_files]
    with Pool(processes=WORKER_COUNT) as pool:
        async_results = [(pool.apply_async(process_file, (task,)), task[0]) for task in tasks]
        for async_result, path in async_results:
            try:
                stats = async_result.get()
                if stats:
                    for entity_type, count in stats.items():
                        total_stats[entity_type] = total_stats.get(entity_type, 0) + count
                    print(f"✓ Processed {path.name}: {stats}")
                else:
                    print(f"✗ No entities found in {path.name}")
            except Exception as e:
                logger.error(f"✗ Failed to process {path.name}: {e}")
    print("=" * 40)
    print("Extraction Summary:")
    for entity_type, count in sorted(total_stats.items()):
        print(f"  {entity_type}: {count}")
    print("=" * 40)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Extract entities (functions, classes, constants) from Python files.")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files or directories to process (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
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
        return 1
    output_dir = Path(args.output).resolve()
    process_entity_extraction(valid_paths, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
