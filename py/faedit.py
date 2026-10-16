import sys
import os
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, TextArea, Static
from textual.binding import Binding
from textual.containers import Vertical

# Import format_persian from your local faprint module/package
try:
    from faprint import format_persian
except ImportError:
    try:
        from core import format_persian
    except ImportError:
        sys.exit("Error: Could not import 'faprint' or 'core'. Ensure faprint is installed or in the same directory.")


class FaEdit(App):
    """Simple Persian Text Editor for Termux using Textual & faprint."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #editor-title {
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    #editor {
        height: 1fr;
        border: solid $accent;
    }
    #preview-title {
        background: $success;
        color: $text;
        padding: 0 1;
    }
    #preview-container {
        height: 1fr;
        border: solid $success;
        padding: 1;
        overflow-y: scroll;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_and_exit", "Save & Exit", show=True),
        Binding("ctrl+q", "quit_without_saving", "Quit Without Saving", show=True),
    ]

    def __init__(self, filename: str):
        super().__init__()
        self.filename = filename
        self.file_content = ""

        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.file_content = f.read()
            except Exception as e:
                print(f"Error reading {self.filename}: {e}")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(" Input (Logical Text) ", id="editor-title")
        yield TextArea(self.file_content, id="editor")
        yield Static(" Live Preview (faprint - Reshaped RTL) ", id="preview-title")

        initial_formatted = format_persian(self.file_content) if self.file_content else ""
        with Vertical(id="preview-container"):
            yield Static(initial_formatted, id="preview")

        yield Footer()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update live faprint preview when text changes."""
        raw_text = event.text_area.text
        formatted_text = format_persian(raw_text) if raw_text else ""
        self.query_one("#preview", Static).update(formatted_text)

    def action_save_and_exit(self) -> None:
        """Save the standard text to file and exit."""
        text_to_save = self.query_one("#editor", TextArea).text
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                f.write(text_to_save)
        except Exception as e:
            self.notify(f"Failed to save: {e}", severity="error")
            return
        self.exit()

    def action_quit_without_saving(self) -> None:
        """Exit without saving changes."""
        self.exit()


def main():
    if len(sys.argv) < 2:
        print("Usage: python faedit.py <filename>")
        sys.exit(1)

    filename = sys.argv[1]
    app = FaEdit(filename)
    app.run()


if __name__ == "__main__":
    main()
