import ast
import io
import time
import tokenize
import multiprocessing
from pathlib import Path

from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory
from dh import DOC_TH1, DOC_TH2

DetectorFactory.seed = 0


TARGET_LANG = "en"
DELAY_SECONDS = 0.5
MAX_WORKERS = 4


SHEBANG_PREFIX = "#!/"
KNOWN_ENGLISH_TOKENS = {
    "TODO",
    "FIXME",
    "HACK",
    "XXX",
    "NOTE",
    "BUG",
    "pylint",
    "noqa",
    "type: ignore",
    "pragma",
    "coding:",
    "encoding:",
    "charset:",
    "DRYRUN",
    "DRY-RUN",
    "RESCURSIVE MODE ENABLED",
    ".gitignore",
}


def should_skip(text: str) -> bool:
    clean = text.strip()

    if clean.startswith(SHEBANG_PREFIX):
        return True

    if clean.isascii():
        if any(word in clean.upper() for word in KNOWN_ENGLISH_TOKENS):
            return True

        if len(clean.split()) <= 2 and len(clean) < 30:
            return True

    if not any(c.isalpha() for c in clean):
        return True

    return False


def is_non_english(text: str) -> bool:
    clean = text.strip()
    if not clean or len(clean) < 4:
        return False
    if should_skip(clean):
        return False
    try:
        return detect(clean) != "en"
    except Exception:
        return False


def translate_text(text: str) -> str:
    try:
        result = GoogleTranslator(source="auto", target=TARGET_LANG).translate(text)
        time.sleep(DELAY_SECONDS)
        return result if result else text
    except Exception as exc:
        print(f"  [warn] translation failed: {exc}")
        return text


def find_print_string_tokens(source: str):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    lines = source.splitlines(keepends=True)

    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode()))

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield arg.value


def process_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    tokens = []

    try:
        token_gen = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in token_gen:
            tokens.append(tok)
    except tokenize.TokenError as exc:
        print(f"[skip] {path}: tokenize error – {exc}")
        return False

    lines = source.splitlines(keepends=True)

    def line_col_to_offset(lineno, col):
        return sum(len(lines[i]) for i in range(lineno - 1)) + col

    replacements = []

    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        raw = tok.string
        inner = raw.lstrip("#").strip()
        if not is_non_english(inner):
            continue

        translated = translate_text(inner)
        print(f"  [comment]\n    orig : {inner}\n    trans: {translated}")

        new_comment = "# " + translated
        start = line_col_to_offset(tok.start[0], tok.start[1])
        end = line_col_to_offset(tok.end[0], tok.end[1])
        replacements.append((start, end, new_comment))

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        print(f"[skip] {path}: ast.parse failed – {exc}")
        return False

    print_arg_positions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    print_arg_positions.add((arg.col_offset, arg.lineno))

    docstring_positions = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                ds = node.body[0].value
                docstring_positions.add((ds.col_offset, ds.lineno))

    for tok in tokens:
        if tok.type != tokenize.STRING:
            continue

        tok_col_offset = tok.start[1]
        tok_lineno = tok.start[0]

        is_print_arg = (tok_col_offset, tok_lineno) in print_arg_positions
        is_docstring = (tok_col_offset, tok_lineno) in docstring_positions

        if not (is_print_arg or is_docstring):
            continue

        raw = tok.string

        if raw.startswith(DOC_TH1) or raw.startswith(DOC_TH2):
            quote = raw[:3]
        elif raw.startswith('"'):
            quote = '"'
        else:
            quote = "'"

        inner = ast.literal_eval(raw)
        if not isinstance(inner, str) or not is_non_english(inner):
            continue

        translated = translate_text(inner)
        label = "docstring" if is_docstring else "print-str"
        print(f"  [{label}]\n    orig : {inner}\n    trans: {translated}")

        escaped = translated.replace("\\", "\\\\").replace(quote, "\\" + quote)
        new_tok = quote + escaped + quote

        start = line_col_to_offset(tok.start[0], tok.start[1])
        end = line_col_to_offset(tok.end[0], tok.end[1])
        replacements.append((start, end, new_tok))

    if not replacements:
        return False

    replacements.sort(key=lambda r: r[0], reverse=True)
    src_chars = list(source)
    for char_start, char_end, new_frag in replacements:
        src_chars[char_start:char_end] = list(new_frag)

    new_source = "".join(src_chars)

    try:
        ast.parse(new_source)
    except SyntaxError as exc:
        print(f"[error] {path}: result is not valid Python – {exc}. Skipping write.")
        return False

    path.write_text(new_source, encoding="utf-8")
    return True


def process_file_wrapper(path_str: str):
    path = Path(path_str)

    try:
        changed = process_file(path)
        status = "updated" if changed else "no changes"

    except Exception as exc:
        print(f"  [error] {path}: {exc}")


def main():
    py_files = [str(p) for p in Path(".").rglob("*.py") if ".git" not in p.parts]

    if not py_files:
        print("No Python files found.")
        return

    print(f"Found {len(py_files)} Python file(s). Starting with {MAX_WORKERS} workers…\n")

    with multiprocessing.Pool(processes=MAX_WORKERS) as pool:
        pool.map(process_file_wrapper, py_files)


if __name__ == "__main__":
    main()
