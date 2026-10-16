import pathlib
import sys

import dh
import rignore


def make_html() -> str:
    header = """<!doctype html>
<html>
<head>
<title>new html</title>
"""
    footer = """</head>
<body>
</body>
</html>
"""
    cssfiles = []
    jsfiles = []
    html = ""
    for pth in rignore.walk("."):
        path = dh.Path(pth)
        if "css" in path.suffix:
            cssfiles.append(path)
        if "js" in path.suffix:
            jsfiles.append(path)
    html = header
    for js in jsfiles:
        jsstr = f"<script src='{js}'></script>"
        html += jsstr
        html += "\n"
    for css in cssfiles:
        cssstr = f"<link rel='stylesheet' href='{css}'>"
        html += cssstr
        html += "\n"
    html += footer
    return html


def main() -> None:
    htmlc = make_html()
    fn = sys.argv[1]
    pathlib.Path(fn).write_text(htmlc, encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
