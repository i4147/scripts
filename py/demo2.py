import os
from weasyprint import HTML

font_dir = "./woff2"
fonts = [f for f in os.listdir(font_dir) if f.endswith((".ttf", ".otf", ".woff", ".woff2"))]
html_content = "<html><head>"
for font in fonts:
    font_name = os.path.splitext(font)[0]
    html_content += f"""
    <style>
        @font-face {{
            font-family: '{font_name}';
            src: url('{font}');
        }}
        .{font_name} {{ font-family: '{font_name}'; }}
    </style>
    """
html_content += "</head><body>"
sample_sentence = "هنر برتز گوهر آمد پدید\n\nThis is a test sentence in the font: {}"
for font in fonts:
    font_name = os.path.splitext(font)[0]
    html_content += f'<p class="{font_name}">{sample_sentence.format(font_name)}</p>'
html_content += "</body></html>"
HTML(string=html_content).write_pdf(output_pdf)
output_pdf
