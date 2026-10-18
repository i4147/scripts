#!/data/data/com.termux/files/usr/bin/python3.12
import sys
import argparse
from pathlib import Path
from multiprocessing import Pool, cpu_count
from dataclasses import dataclass
from typing import List, Tuple
import re
from io import StringIO


@dataclass
class FormatConfig:
    indent_size: int = 2
    align_comments: bool = True
    column_width: int = 80


class TomlLexer:
    TOKEN_PATTERNS = [
        ("COMMENT", r"#[^\n]*"),
        ("MULTILINE_STRING", r'"""(?:[^\\]|\\.)*?"""'),
        ("MULTILINE_LITERAL", r"'''(?:[^\\]|\\.)*?'''"),
        ("STRING", r'"(?:\\.|[^"\\])*"'),
        ("LITERAL", r"'(?:\\.|[^'\\])*'"),
        ("DATETIME", r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})?"),
        ("FLOAT", r"[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?"),
        ("INTEGER", r"[+-]?(?:0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+|\d+)"),
        ("BOOLEAN", r"\b(?:true|false)\b"),
        ("BRACKET_START", r"\["),
        ("BRACKET_END", r"\]"),
        ("BRACE_START", r"\{"),
        ("BRACE_END", r"\}"),
        ("DOT", r"\."),
        ("EQUALS", r"="),
        ("COMMA", r","),
        ("NEWLINE", r"\n"),
        ("WHITESPACE", r"[ \t]+"),
        ("IDENTIFIER", r"[a-zA-Z_][a-zA-Z0-9_-]*"),
    ]

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.tokens = []
        self._tokenize()

    def _tokenize(self):
        while self.pos < len(self.text):
            matched = False
            for token_type, pattern in self.TOKEN_PATTERNS:
                regex = re.compile(pattern)
                match = regex.match(self.text, self.pos)
                if match:
                    value = match.group(0)
                    self.tokens.append((token_type, value, self.line))
                    self.pos = match.end()
                    self.line += value.count("\n")
                    matched = True
                    break
            if not matched:
                raise ValueError(f"Unexpected character at position {self.pos}: {self.text[self.pos]}")

    def get_tokens(self):
        return self.tokens


class TomlParser:
    def __init__(self, tokens: List[Tuple[str, str, int]]):
        self.tokens = tokens
        self.pos = 0
        self.lines = self._group_by_lines()

    def _group_by_lines(self) -> List[List[Tuple[str, str, int]]]:
        lines = []
        current_line = []
        current_line_num = 1
        for token_type, value, line_num in self.tokens:
            if token_type == "NEWLINE":
                current_line.append((token_type, value, line_num))
                lines.append(current_line)
                current_line = []
                current_line_num = line_num + 1
            else:
                current_line.append((token_type, value, line_num))
        if current_line:
            lines.append(current_line)
        return lines

    def parse(self) -> List[dict]:
        result = []
        for line_tokens in self.lines:
            if not line_tokens:
                continue
            line_data = {
                "tokens": line_tokens,
                "raw": "".join(t[1] for t in line_tokens),
                "type": self._determine_line_type(line_tokens),
            }
            result.append(line_data)
        return result

    def _determine_line_type(self, tokens: List[Tuple[str, str, int]]) -> str:
        non_ws = [t for t in tokens if t[0] not in ("WHITESPACE", "NEWLINE")]
        if not non_ws:
            return "empty"
        if non_ws[0][0] == "COMMENT":
            return "comment"
        if any(t[0] == "BRACKET_START" for t in non_ws):
            return "header"
        if any(t[0] == "EQUALS" for t in non_ws):
            return "keyvalue"
        return "other"


class TomlFormatter:
    def __init__(self, config: FormatConfig = None):
        self.config = config or FormatConfig()

    def format(self, content: str) -> str:
        try:
            lexer = TomlLexer(content)
            tokens = lexer.get_tokens()
            parser = TomlParser(tokens)
            lines = parser.parse()
            formatted = self._format_lines(lines)
            return formatted
        except Exception as e:
            raise ValueError(f"Formatting error: {e}")

    def _format_lines(self, lines: List[dict]) -> str:
        output = StringIO()
        current_indent = 0
        for i, line in enumerate(lines):
            formatted_line = self._format_line(line, current_indent)
            # Track indentation based on headers
            if line["type"] == "header":
                bracket_count = formatted_line.count("[")
                current_indent = (bracket_count - 1) * self.config.indent_size
            output.write(formatted_line)
        result = output.getvalue()
        # Remove trailing whitespace and ensure single final newline
        result = "\n".join(line.rstrip() for line in result.split("\n"))
        if result and not result.endswith("\n"):
            result += "\n"
        return result

    def _format_line(self, line: dict, indent: int) -> str:
        if line["type"] == "empty":
            return "\n"
        tokens = line["tokens"]
        # Skip leading whitespace tokens
        content_tokens = [t for t in tokens if t[0] not in ("WHITESPACE", "NEWLINE")]
        if not content_tokens:
            return "\n"
        indent_str = " " * indent
        line_content = ""
        for token_type, value, _ in content_tokens:
            if token_type == "NEWLINE":
                line_content += "\n"
            else:
                line_content += value
        # Add proper spacing around equals
        if line["type"] == "keyvalue":
            line_content = self._format_keyvalue(line_content)
        return indent_str + line_content + "\n"

    def _format_keyvalue(self, line: str) -> str:
        # Match key = value pattern, preserving comments
        match = re.match(r"([^=]+)=(.+)", line)
        if match:
            key = match.group(1).rstrip()
            rest = match.group(2).lstrip()
            return f"{key} = {rest}"
        return line


def validate_toml(content: str) -> bool:
    try:
        lexer = TomlLexer(content)
        parser = TomlParser(lexer.get_tokens())
        parser.parse()
        return True
    except Exception:
        return False


def format_file(file_path: Path, config: FormatConfig) -> Tuple[Path, bool, str]:
    try:
        content = file_path.read_text(encoding="utf-8")
        formatter = TomlFormatter(config)
        formatted = formatter.format(content)
        # Validate before writing
        if not validate_toml(formatted):
            return file_path, False, "Validation failed after formatting"
        file_path.write_text(formatted, encoding="utf-8")
        return file_path, True, "Formatted successfully"
    except Exception as e:
        return file_path, False, f"Error: {str(e)}"


def find_toml_files(start_path: Path) -> List[Path]:
    return list(start_path.rglob("*.toml"))


def main():
    parser = argparse.ArgumentParser(
        description="Format TOML files recursively",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # Format all .toml files in current directory
  %(prog)s path/to/file.toml           # Format specific file
  %(prog)s path/to/directory           # Format all .toml files in directory
  %(prog)s --indent 4 path/to/file.toml  # Use 4-space indentation
        """,
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to format (default: current directory)")
    parser.add_argument("--indent", type=int, default=2, help="Indentation size (default: 2)")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes (default: CPU count)")
    args = parser.parse_args()
    # Determine paths to process
    if not args.paths:
        paths = [Path.cwd()]
    else:
        paths = [Path(p) for p in args.paths]
    # Collect all .toml files
    toml_files = []
    for path in paths:
        if path.is_file() and path.suffix == ".toml":
            toml_files.append(path)
        elif path.is_dir():
            toml_files.extend(find_toml_files(path))
    if not toml_files:
        print("No .toml files found")
        return 0
    # Create config
    config = FormatConfig(indent_size=args.indent)
    # Process files in parallel
    num_workers = args.workers or cpu_count()
    with Pool(num_workers) as pool:
        results = pool.imap_unordered(lambda f: format_file(f, config), toml_files)
        success_count = 0
        failed_files = []
        for file_path, success, message in results:
            if success:
                print(f"✓ {file_path}")
                success_count += 1
            else:
                print(f"✗ {file_path}: {message}")
                failed_files.append(file_path)
    # Summary
    total = len(toml_files)
    print(f"\n{'=' * 60}")
    print(f"Formatted: {success_count}/{total} files")
    if failed_files:
        print(f"\nFailed files:")
        for f in failed_files:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
