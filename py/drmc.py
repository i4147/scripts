import ast
import os
import re
import sys
from pathlib import Path

from dh import DOC_TH1, DOC_TH2, get_pyfiles
from loguru import logger

LANGS = [
    ("Auto-detect by extension", "auto"),
    ("C", "c"),
    ("C++", "cpp"),
    ("C#", "csharp"),
    ("Java", "java"),
    ("JavaScript", "js"),
    ("TypeScript", "ts"),
    ("CSS", "css"),
    ("PHP", "php"),
    ("Rust", "rust"),
    ("Go", "go"),
    ("SQL", "sql"),
    ("Bash / Shell", "bash"),
    ("HTML", "html"),
    ("XML", "xml"),
    ("Python", "python"),
    ("Ruby", "ruby"),
    ("YAML", "yaml"),
    ("TOML", "toml"),
    ("INI", "ini"),
    ("JSON (with comments a.k.a JSONC)", "jsonc"),
]
EXT_TO_LANG = {
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".js": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".css": "css",
    ".rs": "rust",
    ".go": "go",
    ".jsonc": "jsonc",
    ".php": "php",
    ".phtml": "php",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".py": "python",
    ".rb": "ruby",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".json": "jsonc",
}


def auto_detect_language_from_path(path: Path) -> str | None:
    ext = path.suffix.lower()
    return EXT_TO_LANG.get(ext)


def out_path_with_suffix(original: str, suffix: str) -> str:
    folder, base = os.path.split(original)
    name, ext = os.path.splitext(base)
    return os.path.join(folder, f"{name}{suffix}{ext}")


class Result:
    def __init__(self, text: str, comments_found: int, comments_removed_chars: int) -> None:
        self.text = text
        self.comments_found = comments_found
        self.comments_removed_chars = comments_removed_chars


def strip_comments_c_like(src: str, treat_hash_as_line_comment: bool = False, support_backtick: bool = False) -> Result:
    i, n = (0, len(src))
    out = []
    comments = 0
    removed_chars = 0
    IN_STR_SGL, IN_STR_DBL, IN_TEMPLATE = (1, 2, 3)
    state = 0
    template_brace_depth = 0

    def peek(offset: int = 0) -> str:
        j = i + offset
        return src[j] if 0 <= j < n else ""

    nonlocal_i = 0
    while i < n:
        ch = src[i]
        ch2 = src[i + 1] if i + 1 < n else ""
        if state == IN_STR_SGL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == "'":
                state = 0
            i += 1
            continue
        if state == IN_STR_DBL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                state = 0
            i += 1
            continue
        if state == IN_TEMPLATE:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == "`":
                state = 0
                i += 1
                continue
            elif ch == "$" and ch2 == "{":
                template_brace_depth += 1
                out.append(ch2)
                i += 2
                continue
            elif ch == "}" and template_brace_depth > 0:
                template_brace_depth -= 1
            i += 1
            continue
        if ch == "'" and (not support_backtick):
            state = IN_STR_SGL
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            state = IN_STR_DBL
            out.append(ch)
            i += 1
            continue
        if support_backtick and ch == "`":
            state = IN_TEMPLATE
            template_brace_depth = 0
            out.append(ch)
            i += 1
            continue
        if ch == "/" and ch2 == "/":
            comments += 1
            j = i + 2
            while j < n and src[j] not in "\n\r":
                j += 1
            removed_chars += j - i
            i = j
            continue
        if ch == "/" and ch2 == "*":
            comments += 1
            j = i + 2
            while j < n - 1 and (not (src[j] == "*" and src[j + 1] == "/")):
                j += 1
            j = j + 2 if j < n else n
            removed_chars += j - i
            i = j
            continue
        if treat_hash_as_line_comment and ch == "#" and (not (i == 0 and i + 1 < n and (src[i + 1] == "!"))):
            comments += 1
            j = i + 1
            while j < n and src[j] not in "\n\r":
                j += 1
            removed_chars += j - i
            i = j
            continue
        out.append(ch)
        i += 1
    return Result("".join(out), comments, removed_chars)


TRIPLE_STR_OPENERS = (DOC_TH1, DOC_TH2)


def rm_doc(content: str) -> str:
    removed_count = 0
    lines = content.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if DOC_TH1 in line or DOC_TH2 in line:
            delimiter = DOC_TH1 if DOC_TH1 in line else DOC_TH2
            count = line.count(delimiter)
            if count >= 2:
                first = line.find(delimiter)
                second = line.find(delimiter, first + 3)
                before = line[:first].rstrip()
                if before.endswith(":") or before.strip() == "":
                    result_lines.append(line[:first] + line[second + 3 :])
                    removed_count += 1
                    i += 1
                    continue
            before = line[: line.find(delimiter)].rstrip()
            if before.endswith(":") or before.strip() == "" or "=" not in before:
                removed_count += 1
                if before:
                    result_lines.append(before)
                j = i + 1
                while j < len(lines):
                    if delimiter in lines[j]:
                        after = lines[j][lines[j].find(delimiter) + 3 :].strip()
                        if after:
                            result_lines.append(after)
                        i = j + 1
                        break
                    j += 1
                else:
                    i = j
            else:
                result_lines.append(line)
                i += 1
        else:
            result_lines.append(line)
            i += 1
    return "\n".join(result_lines)


def rmsl(data: str):
    lines = data.splitlines(keepends=False)
    nl = []
    removed = 0
    for line in lines:
        stripped = line.lstrip(" ").rstrip(" ").strip()
        if (
            stripped.startswith(DOC_TH1)
            and stripped.endswith(DOC_TH1)
            and ((stripped != DOC_TH1 * 2) and (stripped != DOC_TH1))
        ):
            removed += 1
            continue
        nl.append(line)
    if removed:
        try:
            code = "\n".join(nl)
            ast.parse(code)
            return code
        except:
            return data
    else:
        return data


def strip_comments_python(code: str) -> Result:
    src = ""
    try:
        ast.parse(code)
    except:
        logger.warning("source code isnot valid python code.")
        return None
    streeped = rmsl(code)
    try:
        ast.parse(streeped)
        src = rm_doc(streeped)
    except:
        src = rm_doc(code)
    i, n = (0, len(src))
    out = []
    comments = 0
    removed_chars = 0
    IN_SGL, IN_DBL, IN_TSQ, IN_TDQ = (1, 2, 3, 4)
    state = 0
    while i < n:
        ch = src[i]
        ch2 = src[i + 1] if i + 1 < n else ""
        ch3 = src[i + 2] if i + 2 < n else ""
        if state == IN_SGL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == "'":
                state = 0
            i += 1
            continue
        if state == IN_DBL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                state = 0
            i += 1
            continue
        if state == IN_TSQ:
            out.append(ch)
            if ch == "'" and ch2 == "'" and (ch3 == "'"):
                out.extend((ch2, ch3))
                i += 3
                state = 0
                continue
            i += 1
            continue
        if state == IN_TDQ:
            out.append(ch)
            if ch == '"' and ch2 == '"' and (ch3 == '"'):
                out.extend((ch2, ch3))
                i += 3
                state = 0
                continue
            i += 1
            continue
        if ch == "'" and ch2 == "'" and (ch3 == "'"):
            out.extend((ch, ch2, ch3))
            i += 3
            state = IN_TSQ
            continue
        if ch == '"' and ch2 == '"' and (ch3 == '"'):
            out.extend((ch, ch2, ch3))
            i += 3
            state = IN_TDQ
            continue
        if ch == "'":
            out.append(ch)
            i += 1
            state = IN_SGL
            continue
        if ch == '"':
            out.append(ch)
            i += 1
            state = IN_DBL
            continue
        if ch == "#" and (not (i == 0 and ch2 == "!")):
            comments += 1
            j = i + 1
            while j < n and src[j] not in "\n\r":
                j += 1
            removed_chars += j - i
            i = j
            continue
        out.append(ch)
        i += 1
        final_code = "".join(out)
    try:
        _ = ast.parse(final_code)
        return Result(final_code, comments, removed_chars)
    except:
        print("ast parse error on final code.")
        return Result(src, 0, 0)


def strip_comments_html(src: str) -> Result:
    comments = 0
    removed_chars = 0
    pattern = re.compile(r"<!--[\s\S]*?-->", re.MULTILINE)
    return pattern.sub("", src)


def strip_comments_hash_and_semicolon(src: str, allow_semicolon: bool = True) -> Result:
    comments = 0
    removed = 0
    out_lines = []
    for line in src.splitlines(True):
        i, n = (0, len(line))
        IN_SGL, IN_DBL = (1, 2)
        state = 0
        cut = None
        while i < n:
            ch = line[i]
            if state == IN_SGL:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "'":
                    state = 0
                i += 1
                continue
            if state == IN_DBL:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    state = 0
                i += 1
                continue
            if ch == "'":
                state = IN_SGL
                i += 1
                continue
            if ch == '"':
                state = IN_DBL
                i += 1
                continue
            if ch == "#":
                cut = i
                break
            if allow_semicolon and ch == ";":
                cut = i
                break
            i += 1
        if cut is not None:
            comments += 1
            removed += len(line) - cut
            out_lines.append(line[:cut].rstrip() + ("\n" if line.endswith("\n") else ""))
        else:
            out_lines.append(line)
    return Result("".join(out_lines), comments, removed)


def strip_comments(src: str, lang: str) -> Result:
    lang = lang.lower()
    if lang in {"c", "cpp", "csharp", "java", "css", "rust", "go", "jsonc", "php"}:
        treat_hash = lang == "php"
        return strip_comments_c_like(src, treat_hash_as_line_comment=treat_hash, support_backtick=False)
    if lang in {"js", "ts"}:
        return strip_comments_c_like(src, treat_hash_as_line_comment=False, support_backtick=True)
    if lang == "python":
        return strip_comments_python(src)

    if lang in {"html", "xml"}:
        return strip_comments_html(src)

    if lang == "ruby":
        return strip_comments_ruby(src)

    if lang == "bash":
        return strip_comments_c_like(src, treat_hash_as_line_comment=True, support_backtick=False)

    if lang == "yaml":
        return strip_comments_hash_and_semicolon(src, allow_semicolon=False)

    if lang in {"toml", "ini"}:
        return strip_comments_hash_and_semicolon(src, allow_semicolon=True)
    return strip_comments_c_like(src, treat_hash_as_line_comment=False, support_backtick=False)


def process_file(path: Path, lang: str) -> None:
    src = path.read_text(encoding="utf-8")
    try:
        result = strip_comments(src, lang)
        _ = ast.parse(result)
        backupfile = path.with_name(path.name + ".bak")
        backupfile.write_text(src, encoding="utf8")
        path.write_text(result.text, encoding="utf-8")
    except:
        return


def main() -> None:
    lang = "python"
    args = sys.argv[1:]
    cwd = Path.cwd()
    files = [Path(p) for p in args] if args else get_pyfiles(cwd)
    for f in files:
        process_file(f, lang)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
