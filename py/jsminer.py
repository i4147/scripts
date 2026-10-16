from pathlib import Path
import os
import pathlib
import sys

from jsmin import jsmin


def minify_js_in_directory(root_dir: Path | str = ".") -> None:
    print(f"Starting JavaScript minification in: {pathlib.Path(root_dir).resolve()}")
    print("-" * 40)
    minified_count = 0
    errors_count = 0
    for foldername, _subfolders, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".js"):
                file_path = os.path.join(foldername, filename)
                try:
                    js_content = pathlib.Path(file_path).read_text(encoding="utf-8")
                    minified_content = jsmin(js_content)
                    pathlib.Path(file_path).write_text(minified_content, encoding="utf-8")
                    print(f"✅ Minified: {file_path}")
                    minified_count += 1
                except Exception as e:
                    print(f"❌ ERROR processing {file_path}: {e}", file=sys.stderr)
                    errors_count += 1
    print("-" * 40)
    print("✨ Minification complete!")
    print(f"   Files minified: {minified_count}")
    print(f"   Files with errors: {errors_count}")


if __name__ == "__main__":
    minify_js_in_directory(pathlib.Path.cwd())
