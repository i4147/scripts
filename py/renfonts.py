from pathlib import Path

from fontTools.ttLib import TTFont


def get_font_name(font_path: Path):
    try:
        if font_path.suffix.lower() in {
            ".ttf",
            ".woff",
            ".woff2",
        }:
            font = TTFont(str(font_path))
        else:
            font = TTFont(str(font_path))
        ps_name = font["name"].getName(6, 3, 1, 0, 256)
        if not ps_name:
            family_name = font["name"].getName(
                1,
                3,
                1,
                0,
                256,
            )
            subfamily = font["name"].getName(
                2,
                3,
                1,
                0,
                256,
            )
            if family_name and subfamily:
                return f"{family_name.toUnicode()}-{subfamily.toUnicode()}"
            if family_name:
                return family_name.toUnicode()
        return ps_name.toUnicode()
    except Exception:
        return None


def main() -> None:
    font_extensions = {
        ".ttf",
        ".woff",
        ".woff2",
        ".eot",
    }
    current_dir = Path()
    renamed_count = 0
    skipped_count = 0
    for font_file in current_dir.iterdir():
        if font_file.is_file() and font_file.suffix.lower() in font_extensions:
            font_name = get_font_name(font_file)
            if not font_name:
                skipped_count += 1
                continue
            new_name = f"{font_name}{font_file.suffix}"
            new_name = re.sub(r'[<>:"/\\|?*]', "_", new_name)
            new_name = new_name[:250]
            new_path = font_file.parent / new_name
            if new_path == font_file:
                continue
            if new_path.exists():
                skipped_count += 1
                continue
            try:
                font_file.rename(new_path)
                renamed_count += 1
            except Exception:
                skipped_count += 1


if __name__ == "__main__":
    main()
