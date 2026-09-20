from pathlib import Path
from dh import get_files
from weasyprint import HTML

font_dir = ".ttf"
cwd = Path.cwd()
fonts = get_files(cwd, extensions=[".ttf", ".otf", ".woff", ".woff2"])
html_content = "<html><head>"
for font in fonts:
    font_name = font.stem
    fontstr = str(font)
    html_content += f"""
    <style>
        @font-face {{
            font-family: '{font_name}';
            src: url('{fontstr}');
        }}
        .{font_name} {{ font-family: '{font_name}'; }}
    </style>
    """
html_content += "</head><body>"
sample_sentence = "This is a test sentence in the font: {}"
for font in fonts:
    font_name = font.stem
    html_content += f'<p class="{font_name}">{sample_sentence.format(font_name)}</p>'
html_content += "</body></html>"
output_pdf = "fonts_demo.pdf"
HTML(string=html_content).write_pdf(output_pdf)
