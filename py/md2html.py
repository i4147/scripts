import re
import sys
from pathlib import Path


class MarkdownToHTML:
    def __init__(self) -> None:
        self.lines = []
        self.html_lines = []
        self.in_code_block = False
        self.code_lang = ""

    def convert(self, markdown_text: str) -> str:
        self.lines = markdown_text.split("\\n")
        self.html_lines = []
        self.in_code_block = False
        i = 0
        while i < len(self.lines):
            line = self.lines[i]
            if line.startswith("```"):
                if not self.in_code_block:
                    self.in_code_block = True
                    self.code_lang = line[3:].strip()
                    self.html_lines.append(f'<pre><code class="language-{self.code_lang}">')
                else:
                    self.in_code_block = False
                    self.html_lines.append("</code></pre>")
                i += 1
                continue
            if self.in_code_block:
                self.html_lines.append(self._escape_html(line))
                i += 1
                continue
            heading_match = re.match("^(#{1,6})\\\\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                content = heading_match.group(2)
                self.html_lines.append(f"<h{level}>{self._inline_elements(content)}</h{level}>")
                i += 1
                continue
            if re.match("^(---+|\\\\*\\\\*\\\\*+|___+)$", line):
                self.html_lines.append("<hr />")
                i += 1
                continue
            if line.startswith("> "):
                quote_lines = []
                while i < len(self.lines) and self.lines[i].startswith("> "):
                    quote_lines.append(self.lines[i][2:])
                    i += 1
                self.html_lines.append("<blockquote>")
                self.html_lines.append(f"<p>{self._inline_elements(' '.join(quote_lines))}</p>")
                self.html_lines.append("</blockquote>")
                continue
            ol_match = re.match("^\\\\d+\\\\.\\\\s+(.+)$", line)
            if ol_match:
                self.html_lines.append("<ol>")
                while i < len(self.lines) and re.match("^\\\\d+\\\\.\\\\s+", self.lines[i]):
                    item = re.match("^\\\\d+\\\\.\\\\s+(.+)$", self.lines[i]).group(1)
                    self.html_lines.append(f"<li>{self._inline_elements(item)}</li>")
                    i += 1
                self.html_lines.append("</ol>")
                continue
            ul_match = re.match("^[-*+]\\\\s+(.+)$", line)
            if ul_match:
                self.html_lines.append("<ul>")
                while i < len(self.lines) and re.match("^[-*+]\\\\s+", self.lines[i]):
                    item = re.match("^[-*+]\\\\s+(.+)$", self.lines[i]).group(1)
                    self.html_lines.append(f"<li>{self._inline_elements(item)}</li>")
                    i += 1
                self.html_lines.append("</ul>")
                continue
            if line.strip():
                self.html_lines.append(f"<p>{self._inline_elements(line)}</p>")
            elif self.html_lines and (not self.html_lines[-1].endswith("</p>")):
                self.html_lines.append("<br />")
            i += 1
        return "\\n".join(self.html_lines)

    def _inline_elements(self, text) -> str:
        text = self._escape_html(text)
        text = re.sub("\\\\*\\\\*(.+?)\\\\*\\\\*", "<strong>\\\\1</strong>", text)
        text = re.sub("__(.+?)__", "<strong>\\\\1</strong>", text)
        text = re.sub("\\\\*(.+?)\\\\*", "<em>\\\\1</em>", text)
        text = re.sub("_(.+?)_", "<em>\\\\1</em>", text)
        text = re.sub("`([^`]+)`", "<code>\\\\1</code>", text)
        text = re.sub("\\\\[([^\\\\]]+)\\\\]\\\\(([^)]+)\\\\)", '<a href="\\\\2">\\\\1</a>', text)
        text = re.sub("!\\\\[([^\\\\]]*?)\\\\]\\\\(([^)]+)\\\\)", '<img src="\\\\2" alt="\\\\1" />', text)
        return re.sub("~~(.+?)~~", "<del>\\\\1</del>", text)

    def _escape_html(self, text):
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")
        return text.replace("'", "&#39;")


def create_html_document(content: str, title: str = "Document") -> str:
    return f'<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>{title}</title>\n    <style>\n        body {{\n            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;\n            line-height: 1.6;\n            max-width: 900px;\n            margin: 0 auto;\n            padding: 20px;\n            color:\n            background-color:\n        }}\n        h1, h2, h3, h4, h5, h6 {{\n            margin-top: 24px;\n            margin-bottom: 16px;\n            font-weight: 600;\n            line-height: 1.25;\n        }}\n        h1 {{ font-size: 2em; border-bottom: 1px solid\n        h2 {{ font-size: 1.5em; border-bottom: 1px solid\n        h3 {{ font-size: 1.25em; }}\n        h4 {{ font-size: 1em; }}\n        h5 {{ font-size: 0.875em; }}\n        h6 {{ font-size: 0.85em; color:\n        code {{\n            background-color:\n            border-radius: 3px;\n            padding: 0.2em 0.4em;\n            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;\n            font-size: 0.9em;\n        }}\n        pre {{\n            background-color:\n            border-radius: 6px;\n            padding: 16px;\n            overflow-x: auto;\n            line-height: 1.45;\n        }}\n        pre code {{\n            background-color: transparent;\n            padding: 0;\n            margin: 0;\n        }}\n        blockquote {{\n            padding: 0 1em;\n            color:\n            border-left: 0.25em solid\n            margin: 0 0 16px 0;\n        }}\n        ul, ol {{\n            padding-left: 2em;\n            margin-bottom: 16px;\n        }}\n        li {{\n            margin-bottom: 8px;\n        }}\n        a {{\n            color:\n            text-decoration: none;\n        }}\n        a:hover {{\n            text-decoration: underline;\n        }}\n        img {{\n            max-width: 100%;\n            height: auto;\n            border-radius: 6px;\n        }}\n        hr {{\n            border: none;\n            border-top: 2px solid\n            margin: 24px 0;\n        }}\n        p {{\n            margin-bottom: 16px;\n        }}\n    </style>\n</head>\n<body>\n{content}\n</body>\n</html>'


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python md2html.py <input.md> [output.html]")
        print("       python md2html.py input.md  # Creates input.html")
        sys.exit(1)
    input_file = Path(sys.argv[1])
    if not input_file.exists():
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)
    if len(sys.argv) > 2:
        output_file = Path(sys.argv[2])
    else:
        output_file = input_file.with_suffix(".html")
    try:
        markdown_content = Path(input_file).read_text(encoding="utf-8")
        converter = MarkdownToHTML()
        html_content = converter.convert(markdown_content)
        title = input_file.stem.replace("_", " ").title()
        full_html = create_html_document(html_content, title)
        Path(output_file).write_text(full_html, encoding="utf-8")
        print(f"✓ Successfully converted '{input_file.name}' to '{output_file.name}'")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
