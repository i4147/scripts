import sys
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import List, Dict
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListItem, ListView, Static
from textual.containers import Container
from textual.binding import Binding


@dataclass
class FSItem:
    path: Path
    name: str
    is_dir: bool
    size: int = 0
    items_count: int = 0
    children: List["FSItem"] = field(default_factory=list)
    parent: "FSItem" = None
    flag: str = " "


class DiskAnalyzer:
    def __init__(self, root_path: Path):
        self.root_path = root_path.resolve()

    def scan(self) -> FSItem:
        root_item = FSItem(path=self.root_path, name=str(self.root_path), is_dir=True)
        try:
            top_level_paths = list(self.root_path.iterdir())
        except Exception:
            root_item.flag = "!"
            return root_item
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(self._scan_recursive, p): p for p in top_level_paths}
            for future in concurrent.futures.as_completed(futures):
                child_item = future.result()
                child_item.parent = root_item
                root_item.children.append(child_item)
                root_item.size += child_item.size
                root_item.items_count += child_item.items_count + 1
        root_item.children.sort(key=lambda x: x.size, reverse=True)
        return root_item

    def _scan_recursive(self, path: Path) -> FSItem:
        if path.is_symlink():
            return FSItem(path=path, name=path.name, is_dir=False, size=0, flag="@")
        if path.is_file():
            try:
                return FSItem(path=path, name=path.name, is_dir=False, size=path.stat().st_size)
            except Exception:
                return FSItem(path=path, name=path.name, is_dir=False, size=0, flag="!")
        dir_item = FSItem(path=path, name=path.name, is_dir=True)
        try:
            for child in path.iterdir():
                child_item = self._scan_recursive(child)
                child_item.parent = dir_item
                dir_item.children.append(child_item)
                dir_item.size += child_item.size
                dir_item.items_count += 1
        except Exception:
            dir_item.flag = "!"
        if not dir_item.children and dir_item.flag == " ":
            dir_item.flag = "e"
        dir_item.children.sort(key=lambda x: x.size, reverse=True)
        return dir_item


def format_size(num_bytes: int) -> str:
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:6.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:6.1f} PiB"


def make_progress_bar(item_size: int, max_size: int) -> str:
    if max_size == 0:
        return "[          ]"
    ratio = item_size / max_size
    filled = int(ratio * 10)
    return f"[{'#' * filled}{' ' * (10 - filled)}]"


class GduApp(App):
    CSS = """
    ListView {
        background: $background;
        margin: 1 0;
    }
    ListItem {
        layout: horizontal;
        padding: 0 1;
    }
    .size { width: 12; color: #00ff00; }
    .bar { width: 14; color: #ffff00; }
    .flag { width: 3; color: #ff00ff; }
    .name-dir { color: #00ffff; text-style: bold; }
    .name-file { color: #ffffff; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("enter,l,right", "enter_dir", "Open", show=True),
        Binding("escape,h,left", "back_dir", "Back", show=True),
    ]

    def __init__(self, root_node: FSItem):
        super().__init__()
        self.current_node = root_node

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="current-dir-label", style="background: #333333; padding: 0 1;")
        yield ListView(id="files-list")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "gdu ~ Disk Usage Analyzer (Python Edition)"
        self.update_view()

    def update_view(self) -> None:
        list_view = self.query_one("#files-list", ListView)
        list_view.clear()
        self.query_one("#current-dir-label", Static).update(f"Directory: {self.current_node.path}")
        max_size = max([c.size for c in self.current_node.children], default=1)
        for item in self.current_node.children:
            size_str = format_size(item.size)
            bar_str = make_progress_bar(item.size, max_size)
            flag_str = f"[{item.flag}]" if item.flag != " " else "   "
            name_style = "name-dir" if item.is_dir else "name-file"
            trailing_slash = "/" if item.is_dir else ""
            row_content = f"[span class='size']{size_str}[/][span class='bar']{bar_str}[/][span class='flag']{flag_str}[/][span class='{name_style}']{item.name}{trailing_slash}[/]"
            li = ListItem(Static(row_content))
            li.data = item
            list_view.append(li)

    def action_enter_dir(self) -> None:
        list_view = self.query_one("#files-list", ListView)
        if list_view.index is not None:
            selected_item = list_view.highlighted_child.data
            if selected_item.is_dir and selected_item.children:
                self.current_node = selected_item
                self.update_view()

    def action_back_dir(self) -> None:
        if self.current_node.parent is not None:
            self.current_node = self.current_node.parent
            self.update_view()


if __name__ == "__main__":
    import concurrent.futures

    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    if not target_dir.is_dir():
        print(f"Error: {target_dir} is not a valid directory.")
        sys.exit(1)
    print(f"Scanning {target_dir.resolve()} targets efficiently...")
    analyzer = DiskAnalyzer(target_dir)
    root_node = analyzer.scan()
    app = GduApp(root_node)
    app.run()
