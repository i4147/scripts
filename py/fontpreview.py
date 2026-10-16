import os
from pathlib import Path

FONT_EXTENSIONS = (
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    ".svg",
)
OUTPUT_HTML = "fonts_preview.html"
FONT_SIZES = [22]


def find_fonts(cwd: str = "."):
    fonts = []
    for dirpath, _, filenames in os.walk(cwd):
        fonts.extend(
            os.path.join(dirpath, filename) for filename in filenames if filename.lower().endswith(FONT_EXTENSIONS)
        )
    return fonts


def generate_html(font_files) -> str:
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<title>Font Preview</title>",
        "<link rel=stylesheet src='/sdcard/_static/fontello.css'></link></head>",
        "<body>",
        "<h1>Font Preview</h1>",
    ]
    for font_path in font_files:
        font_name = Path(font_path).name
        html.extend((
            "<div class='font-preview'>",
            "<style>",
            f"@font-face {{ font-family: '{font_name}'; src: url('{font_path}'); }}",
            "</style>",
        ))
        html.extend(
            f"<p style='font-family: \"{font_name}\"; font-size: {size}px;'>({font_path})فارسی</p>"
            for size in FONT_SIZES
        )
        html.append("</div>")
    html.append("</body></html>")
    return "\n".join(html)


def main() -> None:
    fonts = find_fonts()
    if not fonts:
        return
    html_content = generate_html(fonts)
    Path(OUTPUT_HTML).write_text(html_content, encoding="utf-8")
    print("font-preview.html created.")


if __name__ == "__main__":
    main()
