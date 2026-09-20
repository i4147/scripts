import markdown
from weasyprint import HTML

markdown_text = """
This is a **bold** paragraph with some *italic* text.
- List item 1 علیک سلام
- List item 2
"""
css_content = """
@font-face {
    font-family: 'Roya';
    src: url('/sdcard/fonts/ttf/Roya.ttf') format('truetype');
}
@font-face {
    font-family: 'Roboto';
    src: url('/sdcard/fonts/ttf/Roboto.ttf') format('truetype');
}
body {
    font-family: 'Roya', Roboto;
}
h2{font-family: 'Roboto'}
"""
html_string = markdown.markdown(markdown_text)
html_with_css = f"""
<!DOCTYPE html>
<html>
<head>
<style>
{css_content}
</style>
</head>
<body>
{html_string}
</body>
</html>
"""
HTML(string=html_with_css).write_pdf("output.pdf")
print("PDF generated successfully as /mnt/data/output.pdf")
