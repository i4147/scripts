from __future__ import annotations
import argparse
from pathlib import Path
from remove_comments_docstrings import gather_py_files, process_file_tree_sitter, process_file_ast, run_parallel


def main():
    ap = argparse.ArgumentParser(prog="compare_performance.py")
    ap.add_argument("--root", "-r", default=".", help="Root directory to search for .py files (default: current).")
    ap.add_argument("--workers", "-j", type=int, default=None, help="Number of parallel worker processes.")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of files processed (for quick tests).")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    files = gather_py_files(root)
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        print("No Python files found.")
        return 0
    print(f"Comparing on {len(files)} files under {root}")
    print("Timing tree-sitter implementation (dry-run)...")
    changed_ts, errors_ts, elapsed_ts = run_parallel(
        files, process_file_tree_sitter, workers=args.workers, dry_run=True
    )
    print(f"tree-sitter: {elapsed_ts:.3f}s, would change {changed_ts}, errors {len(errors_ts)}")
    print("Timing AST+tokenize implementation (dry-run)...")
    changed_ast, errors_ast, elapsed_ast = run_parallel(files, process_file_ast, workers=args.workers, dry_run=True)
    print(f"ast/tokenize: {elapsed_ast:.3f}s, would change {changed_ast}, errors {len(errors_ast)}")
    if elapsed_ts > 0:
        ratio = elapsed_ast / elapsed_ts
        print(f"Speed ratio: ast/tokenize is {ratio:.2f}x tree-sitter (ratio >1 => ast slower)")
    else:
        print("tree-sitter timing was 0. Cannot compute ratio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
