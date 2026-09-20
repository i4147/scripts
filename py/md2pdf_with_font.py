import markdown
from weasyprint import CSS, HTML

markdown_text = """
This is a paragraph with some text.
- List item 1
- List item 2
"""
html_string = markdown.markdown(markdown_text)
css_file_path = "styles.css"
css = CSS(filename=css_file_path)
HTML(string=html_string).write_pdf("output.pdf", stylesheets=[css])
print("PDF generated successfully as output.pdf")
