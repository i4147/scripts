import os
import shutil
import sys
import mobi

input_file = sys.argv[1]
tempdir, path = mobi.extract(input_file)
print(f"Extracted to: {path}")
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
base_name = os.path.splitext(os.path.basename(input_file))[0]
output_dir = os.path.dirname(os.path.abspath(input_file))
output_file = os.path.join(output_dir, base_name + ".html")
if path.lower().endswith(".epub"):
    extracted_dir = os.path.dirname(path)
    files_dir = os.path.join(output_dir, base_name + "_files")
    if os.path.exists(files_dir):
        shutil.rmtree(files_dir)
    shutil.copytree(extracted_dir, files_dir)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
else:
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
print(f"HTML saved to: {output_file}")
shutil.rmtree(tempdir, ignore_errors=True)
