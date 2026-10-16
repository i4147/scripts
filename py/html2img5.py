from html2image import HtmlImage

hti = HtmlImage()
hti.screenshot(html_string="<h1>Hello</h1>", save_as="output.png")

hti.screenshot(url=url, save_as="output.png")
