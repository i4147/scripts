
import io
import sys
import tokenize
from pathlib import Path

from dh import cprint, get_pyfiles, mpf3

FUNC_NAMES = {"sub", "search", "find", "findall", "match", "finditer", "subn", "split"}
SKIP_TYPES = {
    tokenize.NL,
    tokenize.COMMENT,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.TYPE_COMMENT,
}


def make_raw_and_fix(token_str: str):
    prefix_end = 0
    for ch in token_str:
        if ch in ('"', "'"):
            break
        prefix_end += 1
    else:
        return token_str
    prefix = token_str[:prefix_end]
    if "r" in prefix.lower():
        return token_str
    quote_char = token_str[prefix_end]
    if token_str[prefix_end : prefix_end + 3] == quote_char * 3:
        quote_len = 3
    else:
        quote_len = 1
    opening = quote_char * quote_len
    closing = opening
    content = token_str[prefix_end + quote_len : -quote_len]
    new_content = content.replace("\\\\", "\\")
    new_prefix = "r" + prefix
    return new_prefix + opening + new_content + closing


def process_file(path) -> bool | None:
    path = Path(path)
    code = path.read_text(encoding="utf8")
    bakpath = path.with_name(path.name + ".bak")
    bakpath.write_text(code, encoding="utf8")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except tokenize.TokenError as e:
        print(f"Warning: tokenizing error in {path}: {e}", file=sys.stderr)
        return False
    modifications = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == tokenize.NAME and tok.string == "re":
            j = i + 1
            while j < n and tokens[j].type in SKIP_TYPES:
                j += 1
            if j >= n:
                break
            if tokens[j].type == tokenize.OP and tokens[j].string == ".":
                k = j + 1
                while k < n and tokens[k].type in SKIP_TYPES:
                    k += 1
                if k >= n:
                    break
                if tokens[k].type == tokenize.NAME and tokens[k].string in FUNC_NAMES:
                    l = k + 1
                    while l < n and tokens[l].type in SKIP_TYPES:
                        l += 1
                    if l >= n:
                        break
                    if tokens[l].type == tokenize.OP and tokens[l].string == "(":
                        m = l + 1
                        while m < n and tokens[m].type in SKIP_TYPES:
                            m += 1
                        if m < n and tokens[m].type == tokenize.STRING:
                            str_tok = tokens[m]
                            new_str = make_raw_and_fix(str_tok.string)
                            if new_str != str_tok.string:
                                modifications.append((str_tok.start, str_tok.end, new_str))
        i += 1
    if not modifications:
        return False
    lines = code.splitlines(True)
    line_offsets = [0]
    for line in lines:
        line_offsets.append(line_offsets[-1] + len(line))
    abs_mods = []
    for start, end, new_str in modifications:
        start_abs = line_offsets[start[0] - 1] + start[1]
        end_abs = line_offsets[end[0] - 1] + end[1]
        abs_mods.append((start_abs, end_abs, new_str))
    new_code = code
    for s, e, new in sorted(abs_mods, key=lambda x: x[0], reverse=True):
        new_code = new_code[:s] + new + new_code[e:]
    if new_code and new_code != code:
        path.write_text(new_code, encoding="utf-8")
        cprint(f"Fixed {path}")
        return True
    else:
        print(f"{path.name} error")


if __name__ == "__main__":
    cwd = Path.cwd()
    args = sys.argv[1:]
    files = []

    if args:
        for arg in args:
            p = Path(arg)
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files.extend(get_pyfiles(p))
    else:
        files = get_pyfiles(cwd)

    mpf3(process_file, files)
