from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, TextArea, TabbedContent, Button, Label, Input
from textual.widgets import OptionList, Select
from textual.screen import Screen
from textual.reactive import reactive
from rich.text import Text
from rich.style import Style
from rich.syntax import Syntax
import json
import os
from pathlib import Path
import re


SYNTAX_THEMES = {
    "monokai": {
        "keyword": "bold #F92672",
        "string": "#E6DB74",
        "comment": "#75715E",
        "number": "#AE81FF",
        "function": "#A6E22E",
        "class": "#A6E22E",
        "operator": "#F92672",
        "punctuation": "#F8F8F2",
        "default": "#F8F8F2",
    },
    "dracula": {
        "keyword": "#FF79C6",
        "string": "#F1FA8C",
        "comment": "#6272A4",
        "number": "#BD93F9",
        "function": "#50FA7B",
        "class": "#8BE9FD",
        "operator": "#FF79C6",
        "punctuation": "#F8F8F2",
        "default": "#F8F8F2",
    },
}


class SyntaxHighlighter:
    PATTERNS = {
        "python": {
            "keywords": r"\b(def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|lambda|and|or|not|is|None|True|False|async|await)\b",
            "strings": r"(\".*?\"|\'.*?\'|\"\"\".*?\"\"\"|\'\'\'.*?\'\'\')",
            "comments": r"#.*$",
            "numbers": r"\b\d+(\.\d+)?\b",
            "functions": r"\b\w+(?=\()",
        },
        "javascript": {
            "keywords": r"\b(function|var|let|const|if|else|for|while|return|class|import|export|default|new|this|try|catch|finally|async|await)\b",
            "strings": r"(\".*?\"|\'.*?\'|\`.*?\`)",
            "comments": r"//.*$|/\*.*?\*/",
            "numbers": r"\b\d+(\.\d+)?\b",
            "functions": r"\b\w+(?=\()",
        },
        "html": {
            "tags": r"<[^>]+>",
            "attributes": r"\b\w+(?==)",
            "strings": r"=\".*?\"",
            "comments": r"<!--.*?-->",
        },
        "json": {
            "keys": r"\"\w+\"(?=\s*:)",
            "strings": r":\s*\".*?\"",
            "numbers": r":\s*\d+",
            "booleans": r":\s*(true|false)",
            "null": r":\s*null",
        },
    }

    @classmethod
    def highlight_line(cls, line: str, language: str, theme: str = "monokai") -> Text:
        if language not in cls.PATTERNS:
            return Text(line)

        text = Text(line)
        patterns = cls.PATTERNS[language]
        theme_colors = SYNTAX_THEMES.get(theme, SYNTAX_THEMES["monokai"])

        for pattern_name, pattern in patterns.items():
            color = theme_colors.get(pattern_name, theme_colors["default"])
            for match in re.finditer(pattern, line, re.MULTILINE):
                start, end = match.span()
                text.stylize(Style(color=color), start, end)

        return text


class CommandPaletteScreen(Screen):
    def __init__(self, commands: dict, parent_app) -> None:
        super().__init__()
        self.commands = commands
        self.parent_app = parent_app

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Command Palette (type to filter)", classes="command-title")
            yield Input(placeholder="> ", id="command-input")
            yield OptionList(id="command-list")

    def on_mount(self) -> None:
        self.update_command_list()

    def update_command_list(self, filter_text: str = "") -> None:
        option_list = self.query_one("#command-list", OptionList)
        option_list.clear_options()

        for cmd_name in sorted(self.commands.keys()):
            if filter_text.lower() in cmd_name.lower():
                option_list.add_option(cmd_name)

    @on(Input.Changed, "#command-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_command_list(event.value)

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        cmd_name = event.option.prompt
        if cmd_name in self.commands:
            self.commands[cmd_name]()
            self.app.pop_screen()


class FindReplaceScreen(Screen):
    def __init__(self, text_area, mode: str = "find") -> None:
        super().__init__()
        self.text_area = text_area
        self.mode = mode

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Find:", classes="find-label")
            yield Input(placeholder="Search...", id="find-input")

            if self.mode == "replace":
                yield Label("Replace with:", classes="replace-label")
                yield Input(placeholder="Replace...", id="replace-input")
                yield Button("Replace All", variant="primary", id="replace-all")

            yield Button("Find Next", variant="primary", id="find-next")
            yield Button("Cancel", variant="default", id="cancel")

    @on(Button.Pressed, "#find-next")
    def on_find_next(self) -> None:
        search_term = self.query_one("#find-input", Input).value
        if search_term:
            content = self.text_area.text
            current_pos = self.text_area.cursor_position
            found_pos = content.find(search_term, current_pos + 1)

            if found_pos == -1:
                found_pos = content.find(search_term)

            if found_pos != -1:
                self.text_area.cursor_position = found_pos + len(search_term)
                self.text_area.select_line(found_pos, found_pos + len(search_term))
                self.app.pop_screen()
            else:
                self.notify("No more occurrences found", severity="warning")

    @on(Button.Pressed, "#replace-all")
    def on_replace_all(self) -> None:
        if self.mode == "replace":
            find_term = self.query_one("#find-input", Input).value
            replace_term = self.query_one("#replace-input", Input).value
            if find_term:
                new_text = self.text_area.text.replace(find_term, replace_term)
                self.text_area.text = new_text
                self.notify(f"Replaced all occurrences of '{find_term}'", severity="information")
                self.app.pop_screen()

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.app.pop_screen()


class GoToLineScreen(Screen):
    def __init__(self, text_area) -> None:
        super().__init__()
        self.text_area = text_area

    def compose(self) -> ComposeResult:
        with Container():
            yield Label("Go to Line Number:", classes="goto-label")
            yield Input(placeholder="Line number...", id="line-input")
            yield Button("Go", variant="primary", id="go")
            yield Button("Cancel", variant="default", id="cancel")

    @on(Button.Pressed, "#go")
    def on_go(self) -> None:
        try:
            line_num = int(self.query_one("#line-input", Input).value) - 1
            lines = self.text_area.text.split("\n")
            if 0 <= line_num < len(lines):
                pos = 0
                for i in range(line_num):
                    pos += len(lines[i]) + 1
                self.text_area.cursor_position = pos
                self.text_area.scroll_visible(pos)
                self.app.pop_screen()
            else:
                self.notify("Line number out of range", severity="warning")
        except ValueError:
            self.notify("Invalid line number", severity="error")

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.app.pop_screen()


class FileBrowserScreen(Screen):
    def __init__(self, editor) -> None:
        super().__init__()
        self.editor = editor
        self.current_path = Path.cwd()

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"Current Directory: {self.current_path}", id="path-label")
            yield Input(placeholder="Filter files...", id="filter-input")
            yield OptionList(id="file-list")
            yield Button("Open", variant="primary", id="open")
            yield Button("Cancel", variant="default", id="cancel")

    def on_mount(self) -> None:
        self.update_file_list()

    def update_file_list(self, filter_text: str = "") -> None:
        option_list = self.query_one("#file-list", OptionList)
        option_list.clear_options()

        try:
            items = list(self.current_path.iterdir())
            directories = [item for item in items if item.is_dir()]
            files = [item for item in items if item.is_file()]

            for directory in sorted(directories):
                if not filter_text or filter_text.lower() in directory.name.lower():
                    option_list.add_option(f"📁 {directory.name}/")

            for file in sorted(files):
                if not filter_text or filter_text.lower() in file.name.lower():
                    option_list.add_option(f"📄 {file.name}")
        except PermissionError:
            pass

    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self.update_file_list(event.value)

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        selected = event.option.prompt
        name = selected[2:] if selected.startswith(("📁", "📄")) else selected

        if selected.startswith("📁"):
            new_path = self.current_path / name.rstrip("/")
            if new_path.is_dir():
                self.current_path = new_path
                self.query_one("#path-label", Label).update(f"Current Directory: {self.current_path}")
                self.update_file_list()

    @on(Button.Pressed, "#open")
    def on_open(self) -> None:
        option_list = self.query_one("#file-list", OptionList)
        if option_list.highlighted is not None:
            selected = option_list.get_option_at(option_list.highlighted).prompt
            if selected.startswith("📄"):
                filename = selected[2:]
                filepath = self.current_path / filename
                self.editor.open_file(str(filepath))
                self.app.pop_screen()

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.app.pop_screen()


class StatusBar(Container):
    language = reactive("python")
    cursor_pos = reactive("Ln 1, Col 1")
    file_info = reactive("Ready")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(id="file-info")
            yield Label(id="cursor-pos", classes="status-right")
            yield Label(id="language", classes="status-right")

    def watch_language(self, language: str) -> None:
        self.query_one("#language", Label).update(f"Language: {language}")

    def watch_cursor_pos(self, cursor_pos: str) -> None:
        self.query_one("#cursor-pos", Label).update(cursor_pos)

    def watch_file_info(self, file_info: str) -> None:
        self.query_one("#file-info", Label).update(file_info)


class MiniMap(Vertical):
    def __init__(self, text_area) -> None:
        super().__init__()
        self.text_area = text_area
        self.lines_preview = []

    def compose(self) -> ComposeResult:
        yield ScrollableContainer(id="minimap-content")

    def on_mount(self) -> None:
        self.update_minimap()

    def update_minimap(self) -> None:
        content = self.text_area.text
        lines = content.split("\n")
        total_lines = len(lines)

        container = self.query_one("#minimap-content", ScrollableContainer)
        container.remove_children()

        step = max(1, total_lines // 50)
        for i in range(0, total_lines, step):
            line = lines[i][:30] if lines[i] else "~"
            label = Label(line, classes="minimap-line")
            label.line_number = i
            label.can_focus = False
            container.mount(label)

    def on_click(self, event) -> None:
        if hasattr(event, "target") and hasattr(event.target, "line_number"):
            line_num = event.target.line_number

            content = self.text_area.text
            lines = content.split("\n")
            pos = 0
            for i in range(min(line_num, len(lines))):
                pos += len(lines[i]) + 1
            self.text_area.cursor_position = pos
            self.text_area.scroll_visible(pos)


class EditorTab(Container):
    def __init__(self, filepath: str = None, content: str = "") -> None:
        super().__init__()
        self.filepath = filepath
        self.filename = os.path.basename(filepath) if filepath else "Untitled"
        self.content = content
        self.language = self.detect_language()
        self.modified = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield TextArea(self.content, language=self.language, show_line_numbers=True, id="editor")
            yield StatusBar(id="status-bar")

    def detect_language(self) -> str:
        if not self.filepath:
            return "python"

        ext = os.path.splitext(self.filepath)[1]
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".html": "html",
            ".htm": "html",
            ".json": "json",
            ".txt": "text",
            ".md": "markdown",
        }
        return lang_map.get(ext, "text")

    def update_status(self) -> None:
        content = self.query_one("#editor", TextArea).text
        lines = len(content.split("\n"))
        chars = len(content)
        modified = "✗" if self.modified else "✓"

        status = self.query_one("#status-bar", StatusBar)
        status.file_info = f"{modified} {self.filename} | Ln {lines} | Ch {chars}"
        status.language = self.language

        text_area = self.query_one("#editor", TextArea)
        pos = text_area.cursor_position
        content_before = content[:pos]
        line_num = content_before.count("\n") + 1
        col_num = pos - content_before.rfind("\n") - 1 if "\n" in content_before else pos
        status.cursor_pos = f"Ln {line_num}, Col {col_num + 1}"


class SublimeTextEditor(App):
    CSS = """
    Screen {
        background: $surface;
    }
    
    Header {
        background: $primary;
        color: $text;
    }
    
    TabbedContent {
        height: 1fr;
    }
    
    TextArea {
        height: 1fr;
        background: $surface;
        border: solid $primary;
    }
    
    TextArea:focus {
        border: solid $accent;
    }
    
    .command-title, .goto-label, .find-label, .replace-label {
        padding: 1;
        background: $primary;
        color: $text;
        text-align: center;
    }
    
    #command-input, #find-input, #replace-input, #line-input, #filter-input {
        margin: 1;
    }
    
    OptionList {
        height: 15;
        margin: 1;
        border: solid $primary;
    }
    
    #file-list {
        height: 20;
    }
    
    Button {
        margin: 1;
    }
    
    StatusBar {
        height: 1;
        background: $primary;
        padding: 0 1;
    }
    
    .status-right {
        text-align: right;
        width: 20;
    }
    
    MiniMap {
        width: 20;
        border-left: solid $primary;
        background: $surface-darken-1;
    }
    
    .minimap-line {
        height: 1;
        padding: 0 1;
        overflow: hidden;
        text-style: dim;
    }
    
    .minimap-line:hover {
        background: $accent;
    }
    
    #path-label {
        background: $surface-darken-1;
        padding: 1;
    }
    
    CommandPaletteScreen, FindReplaceScreen, GoToLineScreen, FileBrowserScreen {
        align: center middle;
    }
    
    CommandPaletteScreen > Container, FindReplaceScreen > Container, 
    GoToLineScreen > Container, FileBrowserScreen > Container {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.tabs = []
        self.active_tab_index = 0
        self.theme = "monokai"
        self.show_minimap = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():
            self.tab_container = TabbedContent(initial="tab-0")
            yield self.tab_container

            if self.show_minimap:
                yield MiniMap(id="minimap")

        yield Footer()

    def on_mount(self) -> None:
        self.new_file()
        self.bind_keys()

    def bind_keys(self) -> None:
        self.bind("ctrl+n", "new_file", "New File")
        self.bind("ctrl+o", "open_file", "Open File")
        self.bind("ctrl+s", "save_file", "Save File")
        self.bind("ctrl+shift+s", "save_as", "Save As")
        self.bind("ctrl+w", "close_tab", "Close Tab")
        self.bind("ctrl+f", "show_find", "Find")
        self.bind("ctrl+h", "show_replace", "Replace")
        self.bind("ctrl+g", "show_goto", "Go to Line")
        self.bind("ctrl+shift+p", "show_command_palette", "Command Palette")
        self.bind("ctrl+tab", "next_tab", "Next Tab")
        self.bind("ctrl+shift+tab", "prev_tab", "Previous Tab")
        self.bind("ctrl+b", "toggle_minimap", "Toggle MiniMap")
        self.bind("ctrl+l", "change_language", "Change Language")
        self.bind("ctrl+q", "quit", "Quit")

    def get_current_editor(self) -> TextArea:
        if self.tab_container.active_pane:
            return self.tab_container.active_pane.query_one("#editor", TextArea)
        return None

    def get_current_tab(self) -> EditorTab:
        if self.tab_container.active_pane and isinstance(self.tab_container.active_pane, EditorTab):
            return self.tab_container.active_pane
        return None

    def new_file(self) -> None:
        tab_id = f"tab-{len(self.tabs)}"
        new_tab = EditorTab()
        self.tab_container.add_pane(new_tab, title="Untitled", id=tab_id)
        self.tabs.append(new_tab)
        self.tab_container.active = tab_id

    def open_file(self, filepath: str = None) -> None:
        if not filepath:
            self.push_screen(FileBrowserScreen(self))
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            tab_id = f"tab-{len(self.tabs)}"
            new_tab = EditorTab(filepath, content)
            self.tab_container.add_pane(new_tab, title=os.path.basename(filepath), id=tab_id)
            self.tabs.append(new_tab)
            self.tab_container.active = tab_id

            self.notify(f"Opened {filepath}", severity="information")
        except Exception as e:
            self.notify(f"Error opening file: {str(e)}", severity="error")

    def save_file(self) -> None:
        current_tab = self.get_current_tab()
        editor = self.get_current_editor()

        if not current_tab or not editor:
            return

        if current_tab.filepath:
            try:
                with open(current_tab.filepath, "w", encoding="utf-8") as f:
                    f.write(editor.text)
                current_tab.modified = False
                current_tab.update_status()
                self.notify(f"Saved {current_tab.filename}", severity="information")
            except Exception as e:
                self.notify(f"Error saving file: {str(e)}", severity="error")
        else:
            self.save_as()

    def save_as(self) -> None:

        def save_with_name(filename: str) -> None:
            if filename:
                current_tab = self.get_current_tab()
                editor = self.get_current_editor()
                if current_tab and editor:
                    try:
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(editor.text)
                        current_tab.filepath = filename
                        current_tab.filename = os.path.basename(filename)
                        current_tab.language = current_tab.detect_language()
                        current_tab.modified = False
                        current_tab.update_status()

                        self.tab_container.active_pane.tab.title = current_tab.filename
                        self.notify(f"Saved as {filename}", severity="information")
                    except Exception as e:
                        self.notify(f"Error saving file: {str(e)}", severity="error")

        from textual.widgets import Input

        self.push_screen(InputScreen("Save as: ", save_with_name))

    def close_tab(self) -> None:
        if self.tabs:
            current_tab = self.get_current_tab()
            if current_tab and current_tab.modified:
                self.notify("Please save before closing", severity="warning")
                return

            self.tab_container.remove_pane(self.tab_container.active_pane)
            self.tabs.remove(current_tab)
            if not self.tabs:
                self.new_file()

    def next_tab(self) -> None:
        if len(self.tabs) > 1:
            current_idx = self.tab_container.active_pane_index
            next_idx = (current_idx + 1) % len(self.tabs)
            self.tab_container.active = f"tab-{next_idx}"

    def prev_tab(self) -> None:
        if len(self.tabs) > 1:
            current_idx = self.tab_container.active_pane_index
            prev_idx = (current_idx - 1) % len(self.tabs)
            self.tab_container.active = f"tab-{prev_idx}"

    def show_find(self) -> None:
        editor = self.get_current_editor()
        if editor:
            self.push_screen(FindReplaceScreen(editor, "find"))

    def show_replace(self) -> None:
        editor = self.get_current_editor()
        if editor:
            self.push_screen(FindReplaceScreen(editor, "replace"))

    def show_goto(self) -> None:
        editor = self.get_current_editor()
        if editor:
            self.push_screen(GoToLineScreen(editor))

    def show_command_palette(self) -> None:
        commands = {
            "New File": self.new_file,
            "Open File": self.open_file,
            "Save File": self.save_file,
            "Save As": self.save_as,
            "Close Tab": self.close_tab,
            "Find": self.show_find,
            "Replace": self.show_replace,
            "Go to Line": self.show_goto,
            "Toggle MiniMap": self.toggle_minimap,
            "Change Language": self.change_language,
            "Toggle Line Numbers": self.toggle_line_numbers,
            "Quit": self.quit,
        }
        self.push_screen(CommandPaletteScreen(commands, self))

    def toggle_minimap(self) -> None:
        self.show_minimap = not self.show_minimap
        if self.show_minimap:
            if not self.query("#minimap"):
                self.mount(MiniMap(self.get_current_editor()), after=self.tab_container)
        else:
            minimap = self.query("#minimap")
            if minimap:
                minimap.remove()

    def change_language(self) -> None:
        languages = ["python", "javascript", "html", "json", "text"]

        def set_language(lang: str) -> None:
            editor = self.get_current_editor()
            if editor:
                editor.language = lang
                current_tab = self.get_current_tab()
                if current_tab:
                    current_tab.language = lang
                    current_tab.update_status()
                self.notify(f"Language changed to {lang}", severity="information")

        options = [(lang, lang) for lang in languages]
        self.push_screen(SelectScreen("Select Language:", options, set_language))

    def toggle_line_numbers(self) -> None:
        editor = self.get_current_editor()
        if editor:
            editor.show_line_numbers = not editor.show_line_numbers
            state = "ON" if editor.show_line_numbers else "OFF"
            self.notify(f"Line Numbers: {state}", severity="information")

    @on(TextArea.Changed)
    def on_text_changed(self, event: TextArea.Changed) -> None:
        current_tab = self.get_current_tab()
        if current_tab:
            current_tab.modified = True
            current_tab.update_status()

            if self.show_minimap:
                minimap = self.query("#minimap")
                if minimap:
                    minimap.first().update_minimap()


class InputScreen(Screen):
    def __init__(self, prompt: str, callback) -> None:
        super().__init__()
        self.prompt = prompt
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self.prompt)
            yield Input(id="input")
            yield Button("OK", variant="primary", id="ok")
            yield Button("Cancel", variant="default", id="cancel")

    @on(Button.Pressed, "#ok")
    def on_ok(self) -> None:
        value = self.query_one("#input", Input).value
        self.callback(value)
        self.app.pop_screen()

    @on(Button.Pressed, "#cancel")
    def on_cancel(self) -> None:
        self.app.pop_screen()


class SelectScreen(Screen):
    def __init__(self, title: str, options: list, callback) -> None:
        super().__init__()
        self.title = title
        self.options = options
        self.callback = callback

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(self.title)
            for value, label in self.options:
                yield Button(label, id=f"opt_{value}")
            yield Button("Cancel", variant="default", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("opt_"):
            value = event.button.id[4:]
            self.callback(value)
            self.app.pop_screen()
        elif event.button.id == "cancel":
            self.app.pop_screen()


def main() -> None:
    app = SublimeTextEditor()
    app.run()


if __name__ == "__main__":
    main()
