from io import BytesIO

import fitz
from PIL import Image


def compress_pdf(input_pdf: str, output_pdf: str, dpi=72, quality=50) -> None:
    doc = fitz.open(input_pdf)
    compressed_doc = fitz.open()
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        new_page = compressed_doc.new_page(
            width=page.rect.width,
            height=page.rect.height,
        )
        image_list = page.get_images(full=True)
        for img in image_list:
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image = Image.open(BytesIO(image_bytes))
            original_size = image.size
            new_size = (
                int(original_size[0] * dpi / 300),
                int(original_size[1] * dpi / 300),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            if image.mode in {"RGBA", "P"}:
                image = image.convert("RGB")
            img_buffer = BytesIO()
            image.save(
                img_buffer,
                format="JPEG",
                quality=quality,
                dpi=(dpi, dpi),
            )
            img_buffer.seek(0)
            new_page.insert_image(
                page.rect,
                stream=img_buffer.read(),
            )
    compressed_doc.save(output_pdf)
    compressed_doc.close()
    doc.close()
    print(f"PDF compression completed. Saved as {output_pdf}")


input_pdf = "/content/24102024163001(38mb).pdf"
output_pdf = "compressed_output.pdf"
desired_dpi = 72
jpeg_quality = 80
compress_pdf(
    input_pdf,
    output_pdf,
    dpi=desired_dpi,
    quality=jpeg_quality,
)
