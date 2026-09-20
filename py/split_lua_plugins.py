import sys
import re
import argparse
from pathlib import Path


def split_lua_plugins(input_path, move):
    source = Path(input_path)
    content = source.read_text()

    start_idx = content.find("{")
    end_idx = content.rfind("}")
    if start_idx == -1 or end_idx == -1:
        return

    inner = content[start_idx + 1 : end_idx].strip()

    blocks = []
    current = []
    depth = 0

    for char in inner:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1

        current.append(char)

        if depth == 0 and char == "}":
            block_text = "".join(current).strip()
            if block_text.endswith(","):
                block_text = block_text[:-1].strip()
            blocks.append(block_text)
            current = []
        elif depth == 0 and current and current[-1] == ",":
            current = []

    for block in blocks:
        match = re.search(r'["\']([^"\']+)["\']', block)
        if not match:
            continue

        raw_name = match.group(1)
        plugin_name = raw_name.split("/")[-1].removesuffix(".nvim")

        if plugin_name == "nvim-lspconfig":
            plugin_name = "nvim-lsp-config"

        target = Path(f"{plugin_name}.lua")

        if target.exists():
            target.rename(target.with_suffix(target.suffix + ".orig"))

        target.write_text(f"return {block}")

    if move and blocks:
        source.write_text("return {\n\n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("-m", action="store_true")
    args = parser.parse_args()
    split_lua_plugins(args.file, args.m)
