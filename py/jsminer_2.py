import os
import sys
from jsmin import jsmin


def minify_js_in_directory(root_dir="."):
    print(f"Starting JavaScript minification in: {os.path.abspath(root_dir)}")
    print("-" * 40)
    minified_count = 0
    errors_count = 0
    for foldername, subfolders, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.endswith(".js"):
                file_path = os.path.join(foldername, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        js_content = f.read()
                    minified_content = jsmin(js_content)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(minified_content)
                    print(f"✅ Minified: {file_path}")
                    minified_count += 1
                except Exception as e:
                    print(f"❌ ERROR processing {file_path}: {e}", file=sys.stderr)
                    errors_count += 1
    print("-" * 40)
    print(f"✨ Minification complete!")
    print(f"   Files minified: {minified_count}")
    print(f"   Files with errors: {errors_count}")


if __name__ == "__main__":
    minify_js_in_directory(os.getcwd())
