from termuxgui import Activity, Button, Connection, EditText, LinearLayout, NestedScrollView, TextView

conn = Connection()
act = Activity(conn)
layout = LinearLayout(conn)
act.set_content_view(layout)
pkg_input = EditText(conn, hint="Enter a package name")
layout.add_view(pkg_input)
install_btn = Button(conn, text="Install Package")
layout.add_view(install_btn)
scroll = NestedScrollView(conn)
layout.add_view(scroll)
output_view = TextView(conn, text="")
scroll.add_view(output_view)


def append_output(text: str) -> None:
    current = output_view.get_text()
    output_view.set_text(current + text + "\n")
    scroll.full_scroll(130)


def run_pip_install(pkg) -> None:
    append_output(f"Installing: {pkg}")
    try:
        process = subprocess.Popen(
            ["pip", "install", pkg],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in process.stdout:
            append_output(line.rstrip())
        process.wait()
        if process.returncode == 0:
            append_output(f"Completed: {pkg}")
        else:
            append_output(f"Error: return code {process.returncode}")
    except Exception as e:
        append_output(f"Exception: {e}")


def on_install_click(view) -> None:
    pkg = pkg_input.get_text().strip()
    if not pkg:
        append_output("Enter a package name first.")
        return
    threading.Thread(
        target=run_pip_install,
        args=(pkg,),
        daemon=True,
    ).start()


install_btn.set_on_click(on_install_click)
act.run()
