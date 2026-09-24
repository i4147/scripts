import ast
import io
import re
import shutil
import sys
import tempfile
import tokenize
from pathlib import Path
from deep_translator import GoogleTranslator
from dh import DOC_TH1, DOC_TH2, get_files, mpf3

cwd = Path.cwd()
non_english_pattern = re.compile(r"[^\u00-\u7F]")


def is_english(text: str) -> bool:
    return not non_english_pattern.search(text)


def chunk_text(text: str, size: int = 800) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def translate_chunk(chunk: str) -> str:
    try:
        result = GoogleTranslator(source="auto", target="en").translate(chunk)
        return result or chunk
    except Exception as e:
        print(f"  Translation error for chunk: {e}")
        return chunk


def translate_text(text: str) -> str:
    chunks = chunk_text(text)
    for chunk in chunks:
        translated += translate_chunk(chunk)
    return translated


def safe_overwrite(filepath: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False, dir=filepath.parent) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    shutil.move(tmp_path, filepath)


def extract_docstrings(tree: ast.AST) -> dict[int, str]:
    docstrings = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and not is_english(doc):
                docstrings[id(node)] = doc
    return docstrings


def translate_python_file(source: str) -> str:
    print("  Analyzing Python structure...")
    tree = ast.parse(source)
    docstrings = extract_docstrings(tree)
    if docstrings:
        print(f"  Found {len(docstrings)} non-English docstrings")
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    result = []
    prev_end = 1, 0
    translated_count = 0
    for i, token in enumerate(tokens):
        tok_type, tok_str, start, end, _line = token
        if start > prev_end:
            lines_between = source.splitlines()[prev_end[0] - 1 : start[0]]
            if len(lines_between) > 1:
                result.extend(line_content + "\n" for line_content in lines_between[:-1])
                result.append(lines_between[-1][: start[1]])
            elif lines_between:
                result.append(lines_between[0][prev_end[1] : start[1]])
        if tok_type == tokenize.COMMENT and not is_english(tok_str):
            comment_text = tok_str[1:].strip()
            print(f"  Translating comment: {comment_text[:50]}...")
            translated = translate_text(comment_text)
            result.append(f"# {translated}")
            translated_count += 1
        elif tok_type == tokenize.STRING:
            stripped = tok_str.strip("'\"")
            if stripped and not is_english(stripped) and len(stripped) > 10:
                try:
                    print(f"  Translating string: {stripped[:50]}...")
                    translated = translate_text(stripped)
                    if tok_str.startswith((DOC_TH1, DOC_TH2)):
                        quote_char = tok_str[:3]
                        tok_str = f"{quote_char}{translated}{quote_char}"
                    else:
                        quote_char = tok_str[0]
                        tok_str = f"{quote_char}{translated}{quote_char}"
                    translated_count += 1
                except Exception as e:
                    print(f"  Error translating string: {e}")
            result.append(tok_str)
        else:
            result.append(tok_str)
        prev_end = end
        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1} tokens...")
    print(f"  Translated {translated_count} items")
    return "".join(result)


def process_file(path: (str | Path)) -> None:
    path = Path(path)
    try:
        original = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"  Error reading file: {e}")
        return
    if is_english(original.strip()):
        return
    print("  Translating content...")
    try:
        translated = translate_python_file(original) if path.suffix == ".py" else translate_text(original)
        if translated.strip() != original.strip():
            safe_overwrite(path, translated)
    except:
        return


if __name__ == "__main__":
    args = sys.argv[1:]
    files = [Path(p) for p in args] if args else get_files(cwd)
    mpf3(process_file, files)
