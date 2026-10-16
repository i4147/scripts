import re
import sys
from pathlib import Path


def parse_man_to_md(content) -> str:
    lines = content.split("\n")
    in_synopsis = False
    current_section = "Header"
    markdown_lines = []
    for line in lines:
        line = line.rstrip()
        if re.match("^NAME\\s*$", line) or re.search("NAME\\s*$", line):
            current_section = "NAME"
            markdown_lines.append("## NAME")
            continue
        if re.match("^SYNOPSIS\\s*$", line):
            current_section = "SYNOPSIS"
            markdown_lines.extend(("## SYNOPSIS", "```"))
            in_synopsis = True
            continue
        if re.match("^DESCRIPTION\\s*$", line):
            current_section = "DESCRIPTION"
            markdown_lines.append("## DESCRIPTION")
            continue
        if re.match("^(OPTIONS?|ARGUMENTS?|PARAMETERS?)\\s*$", line, re.IGNORECASE):
            current_section = line.strip().upper()
            markdown_lines.append(f"## {current_section}")
            continue
        if re.match("^[A-Z][A-Z\\s]+$", line) and len(line) < 60:
            current_section = line.strip()
            markdown_lines.append(f"### {current_section}")
            continue
        if in_synopsis:
            if line.strip() == "" or re.match("^[A-Z]+$", line):
                markdown_lines.append("```")
                in_synopsis = False
            else:
                markdown_lines.append(line)
            continue
        line = re.sub("([A-Za-z][A-Za-z0-9._-]+)(?=\\s+\\()", "**\\1**", line)
        line = re.sub("\\b([A-Za-z][A-Za-z0-9-_.]+)\\b(?=\\()", "**\\1**", line)
        line = re.sub("_([^_]+)_", "*\\1*", line)
        line = re.sub('\\.SH\\s+"([^"]+)"', "## \\1", line)
        line = re.sub("\\.B\\s+([^\\s]+)", "**\\1**", line)
        line = re.sub("\\.I\\s+([^\\s]+)", "*\\1*", line)
        line = re.sub("\\.BR\\s+([^\\s]+)", "`\\1`", line)
        line = re.sub("(/[\\w./-]+)", "`\\1`", line)
        line = re.sub("\\b([a-zA-Z0-9][a-zA-Z0-9_-]+)(?=\\()", "`\\1`", line)
        if line.strip():
            markdown_lines.append(line)
    return "\n".join(markdown_lines)


def main() -> None:
    content = sys.stdin.read()
    if not content.strip():
        if len(sys.argv) > 1:
            filename = sys.argv[1]
            try:
                content = Path(filename).read_text(encoding="utf-8")
            except FileNotFoundError:
                sys.exit(1)
        else:
            sys.exit(1)
    md_content = parse_man_to_md(content)
    if len(sys.argv) > 1:
        output_file = Path(sys.argv[1]).with_suffix(".md")
        Path(output_file).write_text(md_content, encoding="utf-8")


if __name__ == "__main__":
    main()
