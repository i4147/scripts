from pathlib import Path

static_dir = "/sdcard/_static"


def fix_links(file_path) -> None:
    content = Path(file_path).read_text(encoding="utf-8")
    links = re.findall(r'href=[\'"]?([^\'" >]+)', content)
    for link in links:
        if not Path(link).exists():
            static_file = static_dir / link
            if static_file.exists():
                content = content.replace(link, str(static_file.resolve()))
                backup_path = file_path.with_suffix(".bak")
                os.replace(file_path, backup_path)
    Path(file_path).write_text(content, encoding="utf-8")


for root, _dirs, files in os.walk("."):
    for file in files:
        if file.endswith((".md", ".html")):
            file_path = Path(root) / file
            fix_links(file_path)
