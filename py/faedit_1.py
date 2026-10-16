#!/data/data/com.termux/files/usr/bin/python3.12
import sys
import os
import argparse
import urwid

# Import backend classes explicitly
import urwid.raw_display
import urwid.curses_display

try:
    from faprint import format_persian
except ImportError:
    try:
        from core import format_persian
    except ImportError:
        sys.exit("Error: Could not import 'faprint' or 'core'.")


class FaEditUrwid:
    def __init__(self, filename: str, backend_name: str):
        self.filename = filename
        self.file_content = ""
        self.backend_name = backend_name

        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    self.file_content = f.read()
            except Exception as e:
                print(f"Error reading {self.filename}: {e}")

        # 1. Setup widgets
        editor_title = urwid.Text(("header", " Input (Logical Text) "))
        preview_title = urwid.Text(("preview_header", " Live Preview (faprint - Reshaped RTL) "))

        # Editor Setup (Multiline Edit wrapped in a scroll box)
        self.editor = urwid.Edit(multiline=True, edit_text=self.file_content)
        editor_filler = urwid.ListBox(urwid.SimpleListWalker([self.editor]))
        editor_box = urwid.LineBox(editor_filler)

        # Preview Setup
        initial_formatted = format_persian(self.file_content) if self.file_content else ""
        self.preview = urwid.Text(initial_formatted)
        preview_filler = urwid.ListBox(urwid.SimpleListWalker([self.preview]))
        preview_box = urwid.LineBox(preview_filler)

        # Connect text change event
        urwid.connect_signal(self.editor, "change", self.on_text_change)

        # 2. Build Layout (Vertical Stack without footer)
        self.layout = urwid.Pile([
            ("flow", editor_title),
            ("weight", 1, editor_box),
            ("flow", preview_title),
            ("weight", 1, preview_box),
        ])

    def on_text_change(self, widget, new_text):
        # Update preview area dynamically on text change
        reshaped = format_persian(new_text)
        self.preview.set_text(reshaped)

    def handle_input(self, key):
        if key in ("ctrl q", "ctrl Q"):
            raise urwid.ExitMainLoop()
        elif key in ("ctrl s", "ctrl S"):
            try:
                with open(self.filename, "w", encoding="utf-8") as f:
                    f.write(self.editor.get_edit_text())
            except Exception as e:
                pass
            raise urwid.ExitMainLoop()

    def run(self):
        if self.backend_name == "curses":
            screen = urwid.curses_display.Screen()
        else:
            screen = urwid.raw_display.Screen()

        palette = [
            ("header", "white", "dark blue", "bold"),
            ("preview_header", "white", "dark red", "bold"),
        ]

        self.loop = urwid.MainLoop(self.layout, palette, screen=screen, unhandled_input=self.handle_input)
        self.loop.run()


def main():
    parser = argparse.ArgumentParser(description="FaEdit: Persian Text Editor Layout")
    parser.add_argument("filename", help="Path to the file to open/edit")
    parser.add_argument(
        "-b",
        "--backend",
        choices=["textual", "urwid", "prompt_toolkit", "curses"],
        default="urwid",
        help="Select the interface rendering backend (default: urwid)",
    )

    args = parser.parse_args()

    app = FaEditUrwid(args.filename, args.backend)
    app.run()


if __name__ == "__main__":
    main()
