import datetime
from pathlib import Path


def generate_project_documentation(root_dir: str = ".", doc_dir_name: str = "doc") -> None:
    root_path = Path(root_dir)
    doc_path = root_path / doc_dir_name
    doc_path.mkdir(exist_ok=True)
    summary_file = doc_path / "project_summary.md"
    history_file = doc_path / "history.txt"
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Documentation directory '{doc_dir_name}' ensured at: {doc_path.resolve()}")
    doc_content = []
    doc_content.extend((
        "# Project Documentation Summary",
        f"**Generated On:** {current_time}",
        f"**Root Directory:** `{root_path.resolve()}`\n",
    ))
    readme_path = root_path / "README.md"
    if readme_path.exists():
        doc_content.append("## Existing README Content")
        try:
            with Path(readme_path).open(encoding="utf-8") as f:
                readme_content = f.read().splitlines()
            doc_content.extend(["> " + line for line in readme_content[:50]])
            if len(readme_content) > 50:
                doc_content.append("> ... (content truncated)")
        except Exception as e:
            doc_content.append(f"Error reading README.md: {e}")
        doc_content.append("\n---\n")
    doc_content.extend(("## Project Structure Overview\n", "```tree"))
    ignore_list = [doc_dir_name, ".git", "__pycache__", ".DS_Store", "venv", "node_modules"]
    for item in sorted(root_path.iterdir()):
        if item.name in ignore_list or item.name.startswith("."):
            continue
        if item.is_dir():
            doc_content.append(f"├── {item.name}/")
            sub_items = [sub.name for sub in item.iterdir() if sub.is_file() and (not sub.name.startswith("."))][:5]
            doc_content.extend((f"│   ├── {sub_name}" for sub_name in sub_items))
            if len(sub_items) == 5:
                doc_content.append("│   └── (...)")
        elif item.is_file():
            doc_content.append(f"└── {item.name}")
    doc_content.append("```\n")
    try:
        Path(summary_file).write_text("\n".join(doc_content), encoding="utf-8")
        print(f"Successfully created/updated main summary file: {summary_file.name}")
    except OSError as e:
        print(f"Error writing summary file: {e}")
        return
    history_entry = f"--- Run Start ---\nTimestamp: {current_time}\nSummary generated at: {summary_file.resolve()}\n--- Run End ---\n\n"
    try:
        with Path(history_file).open("a", encoding="utf-8") as f:
            f.write(history_entry)
        print(f"Successfully logged generation history to: {history_file.name}")
    except OSError as e:
        print(f"Error writing history file: {e}")


if __name__ == "__main__":
    generate_project_documentation()
    print("Documentation generation complete!")
