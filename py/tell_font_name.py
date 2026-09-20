import sys

from fontTools.ttLib import TTFont


def get_font_name(file_path: str):
    try:
        font = TTFont(file_path)
        for record in font["name"].names:
            if record.nameID == 1:
                return record.string.decode("utf-16-be").strip()
    except Exception as e:
        return f"Error: {e}"


font_name = get_font_name(sys.argv[1])
print("Font Name:", font_name)
