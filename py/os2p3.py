import os
import re
from pathlib import Path


def refactor_file(file_path: str) -> None:
    try:
        content = Path(file_path).read_text(encoding="utf-8")
        original_content = content
        content = re.sub(r"os\.path\.join\(([^,]+),\s*([^)]+)\)", "(Path(\g<1>) / \g<2>)", content)
        content = re.sub(r"os\.listdir\(([^)]+)\)", "[f.name for f in Path(\g<1>).iterdir()]", content)
        content = re.sub(r"os\.remove\(([^)]+)\)", "Path(\g<1>).unlink()", content)
        content = re.sub(r"os\.path\.splitext\(([^)]+)\)", "(\x01.stem, \x01.suffix)", content)
        if "import os" in content and "from pathlib import Path" not in content:
            lines = content.splitlines()
            import_path = -1
            for i, line in enumerate(lines):
                if line.strip().startswith("import ") or line.strip().startswith("from "):
                    import_path = i
            if import_path != -1:
                lines.insert(import_path + 1, "from pathlib import Path")
            else:
                lines.insert(0, "from pathlib import Path")
            content = "\n".join(lines)
        if content != original_content:
            Path(file_path).write_text(content, encoding="utf-8")
            print(f"Successfully refactored: {file_path}")
        else:
            print(f"No changes needed for: {file_path}")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")


for root, _dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".py"):
            full_path = os.path.join(root, file)
            print(f"Processing: {full_path}")
            refactor_file(full_path)
print("\nMigration process finished.")
