import os

from weasyprint import HTML

test_sentence = "هنر برتر از گوهر آمد پدید \n\nThis is a test sentence using a custom font. \nهنر برتر از گوهر آمد پدید"
font_extensions = [".ttf", ".otf", ".woff", ".woff2"]
font_files = [f for f in os.listdir("./woff") if os.path.splitext(f)[1].lower() in font_extensions]
if not font_files:
    print("No font files found in the current directory. Please add some .ttf, .otf, .woff, or .woff2 files.")
else:
    html_content_parts = [f"<h1>Font Demo</h1>"]
    for i, font_file in enumerate(font_files):
        font_name = f"CustomFont_{i}"
        css_rule = f"""
        @font-face {{
            font-family: '{font_name}';
            src: url('{font_file}') format('{font_file.split(".")[-1]}');
            font-weight: normal;
            font-style: normal;
        }}
        .font-test-{i} {{
            font-family: '{font_name}', fallback-font, sans-serif; /* Apply custom font with fallbacks */
            font-size: 22px;
            margin-bottom: 15px;
        }}
        """
        html_part = f'<p class="font-test-{i}">{test_sentence} (using: {font_file})</p>'
        html_content_parts.append(f"<style>{css_rule}</style>")
        html_content_parts.append(html_part)
    full_html_content = "".join(html_content_parts)
    output_pdf_filename = "fonts_demo.pdf"
    try:
        base_url = os.path.abspath(".")
        html = HTML(string=full_html_content, base_url=base_url)
        html.write_pdf(output_pdf_filename)
        print(f"PDF generated successfully as {output_pdf_filename}")
        print(f"Files used: {', '.join(font_files)}")
    except OSError as e:
        print(f"Error writing PDF: {e}")
        print("Please ensure the script has write permissions in the current directory.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
