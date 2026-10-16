from tkinter import Text
from tkinter import Button
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
import os
import re


class SyntaxHighlighter:
    PATTERNS = {
        "python": {
            "keywords": r"\b(def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|lambda|and|or|not|is|None|True|False)\b",
            "strings": r"(\".*?\"|\'.*?\')",
            "comments": r"#.*$",
            "numbers": r"\b\d+(\.\d+)?\b",
            "functions": r"\b\w+(?=\()",
        },
        "javascript": {
            "keywords": r"\b(function|var|let|const|if|else|for|while|return|class|import|export|default|new|this|try|catch|finally)\b",
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
    }

    COLORS = {
        "keywords": "#FF6B6B",
        "strings": "#4ECDC4",
        "comments": "#95A5A6",
        "numbers": "#FFE66D",
        "functions": "#45B7D1",
        "tags": "#E74C3C",
        "attributes": "#F39C12",
        "default": "#FFFFFF",
    }

    @classmethod
    def highlight(cls, text_widget: Text, language: str = "python") -> None:

        for tag in text_widget.tag_names():
            if tag.startswith("hl_"):
                text_widget.tag_delete(tag)

        if language not in cls.PATTERNS:
            return

        content = text_widget.get("1.0", tk.END)
        patterns = cls.PATTERNS[language]

        for pattern_name, pattern in patterns.items():
            tag_name = f"hl_{pattern_name}"
            text_widget.tag_configure(tag_name, foreground=cls.COLORS[pattern_name])

            for match in re.finditer(pattern, content, re.MULTILINE):
                start_idx = f"1.0 + {match.start()} chars"
                end_idx = f"1.0 + {match.end()} chars"
                text_widget.tag_add(tag_name, start_idx, end_idx)


class MultiCursor:
    def __init__(self, text_widget) -> None:
        self.text_widget = text_widget
        self.cursors = []
        self.is_active = False

    def add_cursor(self, event=None) -> None:
        index = self.text_widget.index(tk.CURRENT)
        if index not in self.cursors:
            self.cursors.append(index)
            self.update_display()

    def remove_cursor(self, event=None) -> None:
        if self.cursors:
            self.cursors.pop()
            self.update_display()

    def update_display(self) -> None:

        for mark in self.text_widget.mark_names():
            if mark.startswith("cursor_"):
                self.text_widget.mark_unset(mark)

        for i, cursor_pos in enumerate(self.cursors):
            mark_name = f"cursor_{i}"
            self.text_widget.mark_set(mark_name, cursor_pos)
            self.text_widget.mark_gravity(mark_name, tk.RIGHT)

            self.text_widget.tag_delete(f"cursor_tag_{i}")
            self.text_widget.tag_add(f"cursor_tag_{i}", cursor_pos, f"{cursor_pos} + 1 char")
            self.text_widget.tag_configure(f"cursor_tag_{i}", background="#FF6B6B", foreground="white")

    def delete_selection(self) -> None:
        if not self.cursors:
            return

        sorted_cursors = sorted(self.cursors, key=lambda x: int(x.split(".")[0]), reverse=True)

        for cursor in sorted_cursors:
            self.text_widget.delete(cursor, f"{cursor} + 1 char")

        self.cursors = []
        self.update_display()


class CommandPalette:
    def __init__(self, parent, editor) -> None:
        self.parent = parent
        self.editor = editor
        self.window = None

        self.commands = {
            "Save File": self.editor.save_file,
            "Open File": self.editor.open_file,
            "New File": self.editor.new_file,
            "Find": self.editor.find_text,
            "Replace": self.editor.replace_text,
            "Toggle Line Numbers": self.editor.toggle_line_numbers,
            "Change Theme": self.editor.change_theme,
            "Change Syntax": lambda: self.editor.change_syntax(),
            "Multiple Cursor Mode": self.editor.multi_cursor_mode,
            "Exit": self.parent.quit,
        }

    def show(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return

        self.window = tk.Toplevel(self.parent)
        self.window.title("Command Palette")
        self.window.geometry("400x300")
        self.window.configure(bg="#2D2D2D")

        search_label = tk.Label(self.window, text=">", bg="#2D2D2D", fg="#FFFFFF", font=("Consolas", 12))
        search_label.pack(pady=(10, 0))

        self.search_var = tk.StringVar()
        self.search_var.trace("w", self.filter_commands)

        self.search_entry = tk.Entry(
            self.window,
            textvariable=self.search_var,
            bg="#3E3E3E",
            fg="#FFFFFF",
            font=("Consolas", 12),
            insertbackground="white",
        )
        self.search_entry.pack(fill=tk.X, padx=10, pady=5)
        self.search_entry.focus()

        self.listbox = tk.Listbox(
            self.window, bg="#3E3E3E", fg="#FFFFFF", font=("Consolas", 11), selectbackground="#FF6B6B"
        )
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.update_command_list()

        self.listbox.bind("<Double-Button-1>", self.execute_command)
        self.listbox.bind("<Return>", self.execute_command)
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def update_command_list(self) -> None:
        self.listbox.delete(0, tk.END)
        search_term = self.search_var.get().lower()

        for cmd in sorted(self.commands.keys()):
            if search_term in cmd.lower():
                self.listbox.insert(tk.END, cmd)

    def filter_commands(self, *args) -> None:
        self.update_command_list()

    def execute_command(self, event=None) -> None:
        selection = self.listbox.curselection()
        if selection:
            cmd_name = self.listbox.get(selection[0])
            if cmd_name in self.commands:
                self.window.destroy()
                self.commands[cmd_name]()


class MiniMap:
    def __init__(self, parent, text_widget) -> None:
        self.text_widget = text_widget
        self.canvas = tk.Canvas(parent, width=50, bg="#1E1E1E", highlightthickness=0)
        self.canvas.pack(side=tk.RIGHT, fill=tk.Y)
        self.update_minimap()

        self.canvas.bind("<Button-1>", self.jump_to_position)

    def update_minimap(self) -> None:
        self.canvas.delete("all")

        content = self.text_widget.get("1.0", tk.END)
        lines = content.split("\n")

        if not lines:
            return

        total_lines = len(lines)
        height = self.canvas.winfo_height()

        if height <= 1:
            self.canvas.after(100, self.update_minimap)
            return

        line_height = max(1, height / total_lines)

        for i, line in enumerate(lines):
            y1 = i * line_height
            y2 = (i + 1) * line_height

            if line.strip().startswith("#"):
                color = "#4A4A4A"
            elif line.strip().startswith(("def ", "class ")):
                color = "#FF6B6B"
            elif '"' in line or "'" in line:
                color = "#4ECDC4"
            else:
                color = "#2D2D2D"

            self.canvas.create_rectangle(0, y1, 50, y2, fill=color, outline="")

        first_line = int(self.text_widget.index("@0,0").split(".")[0])
        last_line = int(self.text_widget.index("@0,{0}".format(self.text_widget.winfo_height())).split(".")[0])

        vp_y1 = (first_line - 1) * line_height
        vp_y2 = last_line * line_height

        self.canvas.create_rectangle(0, vp_y1, 50, vp_y2, fill="#FF6B6B", outline="", stipple="gray50")

        self.canvas.after(500, self.update_minimap)

    def jump_to_position(self, event) -> None:
        content = self.text_widget.get("1.0", tk.END)
        lines = len(content.split("\n"))
        height = self.canvas.winfo_height()

        if height > 0:
            line_num = int((event.y / height) * lines) + 1
            self.text_widget.see(f"{line_num}.0")


class SublimeTextEditor:
    def __init__(self, root) -> None:
        self.root = root
        self.root.title("Sublime Text Clone")
        self.root.geometry("1200x800")
        self.root.configure(bg="#2D2D2D")

        self.current_file = None
        self.syntax = "python"
        self.show_line_numbers = True
        self.multi_cursor_mode = False

        self.setup_menu()
        self.setup_toolbar()
        self.setup_editor()
        self.setup_status_bar()

        self.multi_cursor = MultiCursor(self.text_area)
        self.command_palette = CommandPalette(root, self)
        self.minimap = None

        self.bind_shortcuts()

        self.root.after(100, self.create_minimap)

        self.new_file()

    def setup_menu(self) -> None:
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        file_menu.add_command(label="Open", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save As", command=self.save_as_file, accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit, accelerator="Ctrl+Q")

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Find", command=self.find_text, accelerator="Ctrl+F")
        edit_menu.add_command(label="Replace", command=self.replace_text, accelerator="Ctrl+H")
        edit_menu.add_separator()
        edit_menu.add_command(label="Toggle Line Numbers", command=self.toggle_line_numbers)
        edit_menu.add_command(label="Multi Cursor Mode", command=self.multi_cursor_mode_toggle)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Command Palette", command=self.command_palette.show, accelerator="Ctrl+Shift+P")
        view_menu.add_command(label="Toggle MiniMap", command=self.toggle_minimap)
        view_menu.add_separator()
        view_menu.add_command(label="Change Syntax", command=self.change_syntax)
        view_menu.add_command(label="Change Theme", command=self.change_theme)

    def setup_toolbar(self) -> None:
        self.toolbar = tk.Frame(self.root, bg="#3E3E3E", height=35)
        self.toolbar.pack(fill=tk.X)

        buttons = [
            ("📄", self.new_file, "New File"),
            ("📂", self.open_file, "Open File"),
            ("💾", self.save_file, "Save File"),
            ("🔍", self.find_text, "Find"),
            ("🎨", self.change_theme, "Change Theme"),
            ("⌨️", self.command_palette.show, "Command Palette"),
        ]

        for text, command, tooltip in buttons:
            btn = tk.Button(
                self.toolbar,
                text=text,
                command=command,
                bg="#3E3E3E",
                fg="#FFFFFF",
                font=("Arial", 12),
                relief=tk.FLAT,
                padx=10,
            )
            btn.pack(side=tk.LEFT, padx=2, pady=2)

            self.create_tooltip(btn, tooltip)

    def create_tooltip(self, widget: Button, text: str) -> None:

        def show_tooltip(event) -> None:
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

            label = tk.Label(tooltip, text=text, background="#FFFFE0", relief=tk.SOLID, borderwidth=1)
            label.pack()

            def hide_tooltip() -> None:
                tooltip.destroy()

            widget.tooltip = tooltip
            widget.bind("<Leave>", lambda e: hide_tooltip())

        widget.bind("<Enter>", show_tooltip)

    def setup_editor(self) -> None:

        self.editor_frame = tk.Frame(self.root, bg="#2D2D2D")
        self.editor_frame.pack(fill=tk.BOTH, expand=True)

        self.line_numbers = tk.Text(
            self.editor_frame,
            width=5,
            padx=3,
            takefocus=0,
            border=0,
            background="#2D2D2D",
            foreground="#858585",
            font=("Consolas", 12),
            state="disabled",
            wrap="none",
        )
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        text_frame = tk.Frame(self.editor_frame)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.text_area = tk.Text(
            text_frame,
            wrap="none",
            undo=True,
            autoseparators=True,
            font=("Consolas", 12),
            bg="#2D2D2D",
            fg="#FFFFFF",
            insertbackground="white",
            selectbackground="#FF6B6B",
            selectforeground="white",
            relief=tk.FLAT,
            padx=10,
            pady=5,
        )

        v_scrollbar = tk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_area.yview)
        h_scrollbar = tk.Scrollbar(self.editor_frame, orient=tk.HORIZONTAL, command=self.text_area.xview)

        self.text_area.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.text_area.bind("<KeyRelease>", self.on_text_change)
        self.text_area.bind("<MouseWheel>", self.on_scroll)
        self.text_area.bind("<Control-Button-1>", self.on_control_click)

    def setup_status_bar(self) -> None:
        self.status_bar = tk.Frame(self.root, bg="#007ACC", height=25)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = tk.Label(
            self.status_bar, text="Ready", bg="#007ACC", fg="white", font=("Arial", 9), anchor="w"
        )
        self.status_label.pack(side=tk.LEFT, padx=5)

        self.cursor_label = tk.Label(self.status_bar, text="Ln 1, Col 1", bg="#007ACC", fg="white", font=("Arial", 9))
        self.cursor_label.pack(side=tk.RIGHT, padx=5)

        self.syntax_label = tk.Label(
            self.status_bar, text=f"Syntax: {self.syntax}", bg="#007ACC", fg="white", font=("Arial", 9)
        )
        self.syntax_label.pack(side=tk.RIGHT, padx=5)

        self.text_area.bind("<KeyRelease>", self.update_cursor_position)
        self.text_area.bind("<ButtonRelease>", self.update_cursor_position)

    def bind_shortcuts(self) -> None:
        self.root.bind("<Control-n>", lambda e: self.new_file())
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_file())
        self.root.bind("<Control-S>", lambda e: self.save_as_file())
        self.root.bind("<Control-f>", lambda e: self.find_text())
        self.root.bind("<Control-h>", lambda e: self.replace_text())
        self.root.bind("<Control-Shift-P>", lambda e: self.command_palette.show())
        self.root.bind("<Control-q>", lambda e: self.root.quit())
        self.root.bind("<Control-d>", lambda e: self.multi_cursor.add_cursor())

    def create_minimap(self) -> None:
        if hasattr(self, "minimap_frame"):
            self.minimap_frame.destroy()

        self.minimap_frame = tk.Frame(self.root)
        self.minimap_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 0))
        self.minimap = MiniMap(self.minimap_frame, self.text_area)

    def update_line_numbers(self, event=None) -> None:
        if not self.show_line_numbers:
            self.line_numbers.pack_forget()
            return
        else:
            self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        lines = int(self.text_area.index("end-1c").split(".")[0])
        line_numbers_str = "\n".join(str(i) for i in range(1, lines + 1))

        self.line_numbers.configure(state="normal")
        self.line_numbers.delete("1.0", tk.END)
        self.line_numbers.insert("1.0", line_numbers_str)
        self.line_numbers.configure(state="disabled")

        self.line_numbers.yview_moveto(self.text_area.yview()[0])

    def on_text_change(self, event=None) -> None:
        self.update_line_numbers()
        SyntaxHighlighter.highlight(self.text_area, self.syntax)
        self.update_status()

    def on_scroll(self, event) -> None:
        self.line_numbers.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_control_click(self, event) -> None:
        if self.multi_cursor_mode:
            self.multi_cursor.add_cursor()

    def update_cursor_position(self, event=None) -> None:
        cursor_pos = self.text_area.index(tk.INSERT)
        line, col = cursor_pos.split(".")
        self.cursor_label.configure(text=f"Ln {line}, Col {int(col) + 1}")

    def update_status(self) -> None:
        char_count = len(self.text_area.get("1.0", tk.END)) - 1
        line_count = len(self.text_area.get("1.0", tk.END).split("\n"))
        self.status_label.configure(text=f"Lines: {line_count} | Characters: {char_count}")

    def new_file(self) -> None:
        self.text_area.delete("1.0", tk.END)
        self.current_file = None
        self.root.title("New File - Sublime Text Clone")
        self.update_status()

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(
            filetypes=[("All Files", "*.*"), ("Text Files", "*.txt"), ("Python Files", "*.py")]
        )
        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as file:
                    content = file.read()
                    self.text_area.delete("1.0", tk.END)
                    self.text_area.insert("1.0", content)
                    self.current_file = filename
                    self.root.title(f"{os.path.basename(filename)} - Sublime Text Clone")
                    self.update_status()
                    self.detect_syntax(filename)
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file: {str(e)}")

    def save_file(self) -> None:
        if self.current_file:
            try:
                content = self.text_area.get("1.0", tk.END).rstrip("\n")
                with open(self.current_file, "w", encoding="utf-8") as file:
                    file.write(content)
                self.update_status()
                messagebox.showinfo("Success", "File saved successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Could not save file: {str(e)}")
        else:
            self.save_as_file()

    def save_as_file(self) -> None:
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("All Files", "*.*"), ("Text Files", "*.txt"), ("Python Files", "*.py")]
        )
        if filename:
            self.current_file = filename
            self.save_file()

    def find_text(self) -> None:
        find_window = tk.Toplevel(self.root)
        find_window.title("Find")
        find_window.geometry("400x100")
        find_window.configure(bg="#2D2D2D")

        tk.Label(find_window, text="Find:", bg="#2D2D2D", fg="white").pack(pady=5)
        find_entry = tk.Entry(find_window, width=50, bg="#3E3E3E", fg="white", insertbackground="white")
        find_entry.pack(pady=5)
        find_entry.focus()

        def find_next() -> None:
            search_term = find_entry.get()
            if search_term:
                content = self.text_area.get("1.0", tk.END)
                start_pos = self.text_area.index(tk.INSERT)
                start_idx = content.find(search_term, self.text_area.index(tk.INSERT))

                if start_idx != -1:
                    end_idx = start_idx + len(search_term)
                    self.text_area.tag_remove(tk.SEL, "1.0", tk.END)
                    self.text_area.tag_add(tk.SEL, f"1.0 + {start_idx} chars", f"1.0 + {end_idx} chars")
                    self.text_area.mark_set(tk.INSERT, f"1.0 + {end_idx} chars")
                    self.text_area.see(tk.INSERT)
                else:
                    messagebox.showinfo("Find", "No more occurrences found")

        tk.Button(find_window, text="Find Next", command=find_next, bg="#007ACC", fg="white").pack(pady=5)
        find_window.bind("<Return>", lambda e: find_next())

    def replace_text(self) -> None:
        replace_window = tk.Toplevel(self.root)
        replace_window.title("Replace")
        replace_window.geometry("400x150")
        replace_window.configure(bg="#2D2D2D")

        tk.Label(replace_window, text="Find:", bg="#2D2D2D", fg="white").pack(pady=2)
        find_entry = tk.Entry(replace_window, width=50, bg="#3E3E3E", fg="white", insertbackground="white")
        find_entry.pack(pady=2)

        tk.Label(replace_window, text="Replace with:", bg="#2D2D2D", fg="white").pack(pady=2)
        replace_entry = tk.Entry(replace_window, width=50, bg="#3E3E3E", fg="white", insertbackground="white")
        replace_entry.pack(pady=2)

        def replace() -> None:
            search_term = find_entry.get()
            replace_term = replace_entry.get()
            if search_term:
                content = self.text_area.get("1.0", tk.END)
                new_content = content.replace(search_term, replace_term)
                self.text_area.delete("1.0", tk.END)
                self.text_area.insert("1.0", new_content)
                messagebox.showinfo("Replace", f"Replaced all occurrences of '{search_term}'")
                replace_window.destroy()

        tk.Button(replace_window, text="Replace All", command=replace, bg="#007ACC", fg="white").pack(pady=5)

    def toggle_line_numbers(self) -> None:
        self.show_line_numbers = not self.show_line_numbers
        self.update_line_numbers()

    def toggle_minimap(self) -> None:
        if hasattr(self, "minimap_frame") and self.minimap_frame.winfo_exists():
            self.minimap_frame.destroy()
        else:
            self.create_minimap()

    def multi_cursor_mode_toggle(self) -> None:
        self.multi_cursor_mode = not self.multi_cursor_mode
        status = "ON" if self.multi_cursor_mode else "OFF"
        self.status_label.configure(text=f"Multi-cursor mode: {status}")

    def detect_syntax(self, filename: str) -> None:
        if filename.endswith(".py"):
            self.syntax = "python"
        elif filename.endswith(".js"):
            self.syntax = "javascript"
        elif filename.endswith((".html", ".htm")):
            self.syntax = "html"
        else:
            self.syntax = "python"

        self.syntax_label.configure(text=f"Syntax: {self.syntax}")
        self.on_text_change()

    def change_syntax(self) -> None:
        syntax_window = tk.Toplevel(self.root)
        syntax_window.title("Change Syntax")
        syntax_window.geometry("300x200")
        syntax_window.configure(bg="#2D2D2D")

        languages = ["python", "javascript", "html"]

        for lang in languages:
            btn = tk.Button(
                syntax_window,
                text=lang.title(),
                command=lambda l=lang: self.set_syntax(l),
                bg="#3E3E3E",
                fg="white",
                font=("Arial", 11),
                width=20,
            )
            btn.pack(pady=5)

    def set_syntax(self, language) -> None:
        self.syntax = language
        self.syntax_label.configure(text=f"Syntax: {self.syntax}")
        self.on_text_change()

    def change_theme(self) -> None:
        color = colorchooser.askcolor(title="Choose Theme Color", color="#2D2D2D")
        if color[1]:
            self.text_area.configure(bg=color[1])
            self.line_numbers.configure(bg=color[1])


def main() -> None:
    root = tk.Tk()
    editor = SublimeTextEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
