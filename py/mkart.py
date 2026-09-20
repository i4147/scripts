def create_arabic_style_art(word):
    letter_art = {
        "ا": [
            "▄▄▄",
            "█▄█",
            "█ █",
            "█ █",
        ],
        "ب": [
            "▄▄▄ ",
            "█▄█ ",
            "█ █▄",
            "▀▀▀ ",
        ],
        "ت": [
            " ▄ ",
            "▄▄▄",
            "█▄█",
            "█ █",
        ],
        "ث": [
            "▄ ▄",
            "▄▄▄",
            "█▄█",
            "█ █",
        ],
        "ج": [
            " ▄▄▄",
            "█▄█ ",
            "█ █ ",
            "▀▀▀ ",
        ],
        "ح": [
            " ▄▄▄",
            "█▄█ ",
            "█ █ ",
            "█ █ ",
        ],
        "خ": [
            "▄ ▄▄▄",
            " █▄█ ",
            " █ █ ",
            " █ █ ",
        ],
        "د": [
            "▄▄ ",
            "█▄█",
            "█ █",
            "█ █",
        ],
        "ذ": [
            "▄ ▄▄",
            " █▄█",
            " █ █",
            " █ █",
        ],
        "ر": [
            "▄▄ ",
            "█▄█",
            "█ █",
            "▀ ▀",
        ],
        "ز": [
            "▄ ▄▄",
            " █▄█",
            " █ █",
            " ▀ ▀",
        ],
        "س": [
            "▄▄▄▄",
            "█▄█▄",
            "█ █ ",
            "▀▀▀ ",
        ],
        "ش": [
            "▄ ▄▄▄▄",
            " █▄█▄ ",
            " █ █  ",
            " ▀▀▀  ",
        ],
        "ص": [
            "▄▄▄▄▄",
            "█▄█▄█",
            "█ █ █",
            "▀▀▀▀▀",
        ],
        "ض": [
            "▄ ▄▄▄▄▄",
            " █▄█▄█ ",
            " █ █ █ ",
            " ▀▀▀▀▀ ",
        ],
        "ط": [
            "▄▄▄ ",
            "█▄█ ",
            "█ █▄",
            "▀▀▀ ",
        ],
        "ظ": [
            "▄ ▄▄▄",
            " █▄█ ",
            " █ █▄",
            " ▀▀▀ ",
        ],
        "ع": [
            "▄▄▄▄",
            "█▄█▄",
            "█ █ ",
            "▀▀▀ ",
        ],
        "غ": [
            "▄ ▄▄▄▄",
            " █▄█▄ ",
            " █ █  ",
            " ▀▀▀  ",
        ],
        "ف": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █ ",
            "▀▀▀ ",
        ],
        "ق": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █▄",
            "▀▀▀ ",
        ],
        "ك": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █ ",
            "▀ ▀ ",
        ],
        "ل": [
            "▄▄▄ ",
            "█▄█ ",
            "█ █ ",
            "▀ ▀ ",
        ],
        "م": [
            "▄▄▄▄",
            "█▄█▄",
            "█ █ ",
            "▀▀▀ ",
        ],
        "ن": [
            "▄▄▄ ",
            "█▄█ ",
            "█ █▄",
            "▀▀▀ ",
        ],
        "ه": [
            "▄▄▄▄",
            "█▄█▄",
            "█ █▄",
            "▀▀▀ ",
        ],
        "و": [
            "▄▄ ",
            "█▄█",
            "█ █",
            "▀ ▀",
        ],
        "ي": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █▄",
            "▀▀▀ ",
        ],
        " ": [
            "   ",
            "   ",
            "   ",
            "   ",
        ],
    }

    if not word:
        return []

    chars = list(word)

    num_rows = 4

    art_lines = []
    for row in range(num_rows):
        line = ""
        for char in chars:
            if char in letter_art:
                line += letter_art[char][row]
            else:
                line += "   "
        art_lines.append(line)

    return art_lines


def main():
    print("Arabic Calligraphy Text Art Generator")
    print("=" * 40)
    print("Enter text to convert (Arabic letters supported)")
    print("Type 'quit' to exit")
    print()

    while True:
        text = input("Enter text: ").strip()

        if text.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break

        if not text:
            print("Please enter some text.")
            continue

        art = create_arabic_style_art(text)

        print("\n" + "=" * 40)
        for line in art:
            print(f'    "{line}",')
        print("=" * 40)
        print()


if __name__ == "__main__":
    main()
