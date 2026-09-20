
import ast
import collections
import json
from multiprocessing import Pool
from multiprocessing.pool import AsyncResult
from pathlib import Path
from typing import Any, Final, Optional, cast

import astor  
from loguru import logger

REPEATED_JSON_PATH: Final[Path] = Path("repeated.json")
MAX_WORKERS: Final[int] = 8

FileMap = dict[str, list[str]]
Task = tuple[Path, list[str]]


def load_refactoring_maps() -> FileMap:
    with REPEATED_JSON_PATH.open("r", encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)

    file_to_objects: collections.defaultdict[str, list[str]] = collections.defaultdict(list)
    for item in data:
        obj_name: str = item["name"]
        for file_path_str in item["files"]:
            p: Path = Path(file_path_str)
            file_to_objects[p.name].append(obj_name)

    return dict(file_to_objects)


class ASTStripper(ast.NodeTransformer):

    def __init__(self, target_names: list[str]) -> None:
        super().__init__()
        self.target_names: set[str] = set(target_names)
        self.removed_something: bool = False

    def visit_FunctionDef(  
        self, node: ast.FunctionDef
    ) -> Optional[ast.FunctionDef]:
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return cast(ast.FunctionDef, self.generic_visit(node))

    def visit_AsyncFunctionDef(  
        self, node: ast.AsyncFunctionDef
    ) -> Optional[ast.AsyncFunctionDef]:
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return cast(ast.AsyncFunctionDef, self.generic_visit(node))

    def visit_ClassDef(  
        self, node: ast.ClassDef
    ) -> Optional[ast.ClassDef]:
        if node.name in self.target_names:
            self.removed_something = True
            return None
        return cast(ast.ClassDef, self.generic_visit(node))

    def visit_Assign(  
        self, node: ast.Assign
    ) -> Optional[ast.Assign]:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in self.target_names:
                self.removed_something = True
                return None
        return cast(ast.Assign, self.generic_visit(node))


def refactor_single_file(file_path: Path, objects_to_remove: list[str]) -> bool:
    try:
        source_code: str = file_path.read_text(encoding="utf-8")
        tree: ast.Module = ast.parse(source_code)
    except Exception as exc:
        logger.error(f"❌ Error parsing {file_path.name}: {exc}")
        return False

    stripper: ASTStripper = ASTStripper(objects_to_remove)
    modified_tree: ast.AST = stripper.visit(tree)
    ast.fix_missing_locations(modified_tree)

    if not stripper.removed_something:
        logger.info(f"➖ No matching structural nodes found inside {file_path.name}")
        return False

    import_names: str = ", ".join(sorted(objects_to_remove))
    import_statement: str = f"from dh import {import_names}\n"

    try:
        cleaned_source: str = astor.to_source(modified_tree)
    except Exception as exc:
        logger.error(f"❌ Failed to stringify AST for {file_path.name}: {exc}")
        return False

    lines: list[str] = cleaned_source.splitlines(keepends=True)
    insert_idx: int = 0
    if lines and lines[0].startswith("#!"):
        insert_idx = 1
    if len(lines) > insert_idx and (
        lines[insert_idx].strip().startswith('"""') or lines[insert_idx].strip().startswith("'''")
    ):
        insert_idx += 1

    lines.insert(insert_idx, import_statement)

    try:
        file_path.write_text("".join(lines), encoding="utf-8")
        logger.info(f"✅ Refactored {file_path.name}: Stripped {objects_to_remove} -> added 'dh' import")
        return True
    except Exception as exc:
        logger.error(f"❌ Error writing updates back to {file_path.name}: {exc}")
        return False


def main() -> None:
    if not REPEATED_JSON_PATH.exists():
        logger.error(f"Error: {REPEATED_JSON_PATH.name} not found in the current directory.")
        return

    refactor_map: FileMap = load_refactoring_maps()
    current_dir: Path = Path(".")
    local_files: dict[str, Path] = {f.name: f for f in current_dir.glob("*.py")}

    tasks: list[Task] = [
        (local_files[filename], objects) for filename, objects in refactor_map.items() if filename in local_files
    ]

    if not tasks:
        logger.info("No matching files found in the current directory to refactor.")
        return

    logger.info(f"🚀 Found {len(tasks)} files to clean structural code from. Starting parallel processing...")

    with Pool(processes=MAX_WORKERS) as pool:
        async_results: list[AsyncResult[bool]] = [
            pool.apply_async(refactor_single_file, (file_path, objects)) for file_path, objects in tasks
        ]
        for async_res in async_results:
            try:
                async_res.get()
            except Exception as exc:
                logger.error(f"❌ Worker raised: {exc}")

    logger.info("🎉 Structural refactoring complete! All duplicate bodies stripped.")


if __name__ == "__main__":
    raise SystemExit(main())
