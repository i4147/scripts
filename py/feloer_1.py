#!/data/data/com.termux/files/usr/bin/python
import argparse
import asyncio
import ast
import fnmatch
from os import environ
from pathlib import Path
import re
import subprocess
import sys
from dh import DOC_TH1, DOC_TH2

FELO_SUPERAGENT = "/data/data/com.termux/files/home/bashbin/felo-sa.mjs"
FELO_TIMEOUT = int(environ.get("FELO_TIMEOUT", "300"))
PROMPT_TEMPLATE = """
You are an expert software requirements writer. Analyze the Python code below and write a clear, high-level prompt or specification that can be given to an AI coding agent to build a similar script from scratch. The prompt must begin with a phrase like "Write a Python script that..." or "Generate a Python tool that...". Focus strictly on the high-level purpose, main inputs and outputs, and key behaviors. Do NOT describe the code line-by-line, and do not restrict low-level implementation details such as specific function names, loop types, internal variables, or imported libraries, allowing the AI complete creative freedom. Do not include code snippets. Output only the generated prompt in English without explanations or preamble.
Python code:
{code}
"""
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
FENCE_RE = re.compile(r"^\s*```.*$", re.MULTILINE)
SHELL_PROMPT_RE = re.compile(r"^\s*(?:\$|>|>>>)\s.*$", re.MULTILINE)
PREAMBLE_RE = re.compile(
    r"^(?:sure[,!.]?|certainly[,!.]?|here(?:'s| is)[^\n]*|of course[,!.]?)\s*\n",
    re.IGNORECASE,
)
LIVEDOC_RE = re.compile(r"^\s*LiveDoc\s*:.*$", re.MULTILINE | re.IGNORECASE)


class CodeMangler(ast.NodeTransformer):
    def visit_Module(self, node: ast.Module) -> ast.Module:
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
        new_body: list[ast.stmt] = []
        for stmt in node.body:
            if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
                continue
            new_body.append(self.visit(stmt))
        node.body = new_body
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
        node.returns = None
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            arg.annotation = None
        if node.args.vararg:
            node.args.vararg.annotation = None
        if node.args.kwarg:
            node.args.kwarg.annotation = None
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        if node.value is not None:
            return ast.Assign(targets=[node.target], value=node.value)
        return ast.Pass()


def mangle_code(code: str) -> str:
    try:
        tree = ast.parse(code)
        transformer = CodeMangler()
        new_tree = transformer.visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)
    except Exception:
        return code


def clean_response(text: str) -> str:
    lower_text = text.lower()
    refusal_markers = [
        "truncated",
        "cut off",
        "paste",
        "mid-line",
        "can't produce",
        "cannot produce",
        "complete file",
    ]
    if any(marker in lower_text for marker in refusal_markers):
        return ""
    text = ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    m = re.search(r"^\s*Received\s*:", text, re.MULTILINE | re.IGNORECASE)
    if m:
        after = text[m.end() :]
        after = after.split("\n", 1)[1] if "\n" in after else ""
        after = re.sub(r"^\s*\n+", "", after)
        text = after
    text = re.sub(
        r"^\s*(?:SuperAgent|felo|feli)\b.*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    text = FENCE_RE.sub("", text)
    text = SHELL_PROMPT_RE.sub("", text)
    text = PREAMBLE_RE.sub("", text)
    text = LIVEDOC_RE.sub("", text)
    text = text.strip()
    if not text:
        return ""
    if "\n" not in text:
        parts = re.split(r"(?<=[.!?])\s+", text)
        text = "\n".join(p.strip() for p in parts if p.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def make_docstring(text: str) -> str:
    safe = re.sub(r"\\", r"\\\\", text)
    safe = re.sub(r'"""', r'\\"\\"\\"', safe)
    return DOC_TH1 + safe + DOC_TH1 + "\n\n"


def split_header(body: str) -> tuple[str, str]:
    lines = body.split("\n")
    idx = 0
    if lines and lines[0].startswith("#!"):
        idx = 1
    if idx < len(lines) and re.match(r"^#.*coding[:=]", lines[idx]):
        idx += 1
    if idx == 0:
        return "", body
    return "\n".join(lines[:idx]) + "\n", "\n".join(lines[idx:])


def has_module_docstring(body: str) -> bool:
    s = body.lstrip()
    return s.startswith((DOC_TH1, DOC_TH2))


def strip_module_docstring(body: str) -> str:
    s = body.lstrip()
    quote = None
    if s.startswith(DOC_TH1):
        quote = DOC_TH1
    elif s.startswith(DOC_TH2):
        quote = DOC_TH2
    if not quote:
        return body
    end_idx = s.find(quote, len(quote))
    if end_idx != -1:
        return s[end_idx + len(quote) :].lstrip("\r\n")
    return body


async def ask_felo(code: str) -> str:
    mangled = mangle_code(code)
    prompt = PROMPT_TEMPLATE.format(code=mangled)
    cmd = [
        "node",
        FELO_SUPERAGENT,
        "--query",
        prompt,
        "--accept-language",
        "en",
        "--timeout",
        "300",
        "--verbose",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=float(FELO_TIMEOUT))
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise subprocess.TimeoutExpired(cmd, FELO_TIMEOUT)
    if proc.returncode != 0:
        msg = f"felo exited {proc.returncode}: {stderr.decode('utf-8', errors='replace').strip()[:300]}"
        raise RuntimeError(msg)
    return stdout.decode("utf-8", errors="replace")


async def annotate(path: Path, dry_run: bool, force: bool, sem: asyncio.Semaphore, stats: dict[str, int]) -> None:
    async with sem:
        if path.name in {
            "__init__.py",
            "__main__.py",
            "setup.py",
            "main.py",
            "test.py",
            "conf.py",
            "tests.py",
        }:
            stats["skipped_ignored"] += 1
            return
        if path.stat().st_size > 30 * 1024:
            stats["skipped_size"] += 1
            return
        content = path.read_text(encoding="utf-8")
        header, body = split_header(content)
        if has_module_docstring(body):
            if not force:
                stats["skipped_docstring"] += 1
                return
            body = strip_module_docstring(body)
        try:
            raw = await ask_felo(content)
        except FileNotFoundError:
            sys.exit("ERROR: node CLI not found in PATH.")
        except subprocess.TimeoutExpired:
            stats["errors"] += 1
            return
        except RuntimeError:
            stats["errors"] += 1
            return
        cleaned = clean_response(raw)
        if not cleaned:
            stats["errors"] += 1
            return
        docstring = make_docstring(cleaned)
        new_content = header + docstring + body
        if dry_run:
            stats["success"] += 1
            return
        path.write_text(new_content, encoding="utf-8")
        stats["success"] += 1


def collect_files(inputs: list[str], pattern: str) -> list[Path]:
    me = Path(__file__).resolve()
    seen: set[Path] = set()
    out: list[Path] = []

    def add(p: Path) -> None:
        ap = p.resolve()
        if ap == me:
            return
        if ap in seen:
            return
        seen.add(ap)
        out.append(ap)

    for inp in inputs:
        inp_path = Path(inp)
        if inp_path.is_file():
            add(inp_path)
        elif inp_path.is_dir():
            for root, _dirs, names in inp_path.walk():
                for name in names:
                    if fnmatch.fnmatch(name, pattern):
                        add(root / name)
    return sorted(out)


async def process_paths(paths: list[Path], dry_run: bool, force: bool, concurrency: int, delay: float) -> None:
    sem = asyncio.Semaphore(concurrency)
    stats = {
        "success": 0,
        "skipped_size": 0,
        "skipped_docstring": 0,
        "skipped_ignored": 0,
        "errors": 0,
    }
    async with asyncio.TaskGroup() as tg:
        for p in paths:
            tg.create_task(annotate(p, dry_run, force, sem, stats))
            if delay > 0:
                await asyncio.sleep(delay)
    print("\n--- Execution Summary ---")
    print(f"Successfully processed:     {stats['success']}")
    print(f"Skipped (>30KB limit):      {stats['skipped_size']}")
    print(f"Skipped (docstring exists): {stats['skipped_docstring']}")
    print(f"Skipped (ignored filename): {stats['skipped_ignored']}")
    print(f"Errors / Empty responses:   {stats['errors']}")


def main() -> None:
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "paths",
        nargs="*",
        help="One or more files or directories. If omitted, current directory is processed recursively.",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwrite existing module docstrings.",
    )
    ap.add_argument(
        "--pattern",
        default="*.py",
        help="Glob pattern used when expanding directories (default: *.py).",
    )
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument(
        "-j",
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent workers.",
    )
    args = ap.parse_args()
    inputs = args.paths or ["."]
    paths = collect_files(inputs, args.pattern)
    if not paths:
        print(f"No matching files found (pattern={args.pattern!r}).")
        return
    asyncio.run(process_paths(paths, args.dry_run, args.force, args.concurrency, args.delay))


if __name__ == "__main__":
    main()
