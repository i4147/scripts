import argparse
import concurrent.futures
import os
import tokenize
import warnings
from pathlib import Path

from dh import get_pyfiles_iter
from fastwalk import walk_files


def process_file(file_path: Path, auto_fix: bool = True) -> dict:
    result = {"path": file_path, "has_issues": False, "fixed": False, "messages": []}
    try:
        content_bytes = file_path.read_bytes()
    except Exception as e:
        result["messages"].append(f"Error reading file: {e}")
        return result
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always", SyntaxWarning)
        try:
            compile(content_bytes, str(file_path), "exec")
        except SyntaxError as se:
            if "invalid escape sequence" in str(se):
                result["has_issues"] = True
                result["messages"].append(f"Line {se.lineno}: SyntaxError: {se.msg}")
            else:
                return result
        for w in caught_warnings:
            if issubclass(w.category, SyntaxWarning) and "invalid escape sequence" in str(w.message):
                result["has_issues"] = True
                line_no = getattr(w, "lineno", "Unknown")
                result["messages"].append(f"Line {line_no}: SyntaxWarning: {w.message}")
    if result["has_issues"] and auto_fix:
        try:
            modified_tokens = []
            is_modified = False
            with file_path.open("rb") as f:
                tokens = list(tokenize.tokenize(f.readline))
            for tok in tokens:
                if tok.type == tokenize.STRING:
                    text = tok.string
                    prefix = ""
                    for char in text:
                        if char.lower() in "frub":
                            prefix += char
                        else:
                            break
                    actual_str = text[len(prefix) :]
                    if "\\" in actual_str and "r" not in prefix.lower():
                        with warnings.catch_warnings(record=True) as token_warnings:
                            warnings.simplefilter("always", SyntaxWarning)
                            try:
                                compile(f"_{prefix}{actual_str}", "<string>", "exec")
                            except (SyntaxError, SyntaxWarning):
                                pass
                            if any("invalid escape sequence" in str(tw.message) for tw in token_warnings):
                                new_prefix = "r" + prefix
                                tok = tok._replace(string=f"{new_prefix}{actual_str}")
                                is_modified = True
                modified_tokens.append(tok)
            if is_modified:
                fixed_bytes = tokenize.untokenize(modified_tokens)
                file_path.write_bytes(fixed_bytes)
                result["fixed"] = True
        except Exception as e:
            result["messages"].append(f"Error while fixing: {e}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Recursively scan and fix Python files for invalid escape sequences.")
    parser.add_argument(
        "-a",
        "--auto-fix",
        action="store_true",
        help="Automatically fix issues by converting offending string literals to raw strings.",
    )
    args = parser.parse_args()
    cwd = Path.cwd()
    for path in walk_files(cwd):
        path = Path(path)
        if path.suffix == ".py":
            print(f"processing {path.name}")
            process_file(path)


if __name__ == "__main__":
    main()
