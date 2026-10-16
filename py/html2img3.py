from weasyprint import HTML

HTML(url).write_png("output.png")

HTML("index.html").write_png("output.png")
