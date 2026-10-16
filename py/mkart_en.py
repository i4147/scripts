def create_english_style_art(word):
    letter_art = {
        "A": [
            "▄▄▄ ",
            "█▄█ ",
            "█ █ ",
            "▀ ▀ ",
        ],
        "B": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █▄",
            "▀▀▀ ",
        ],
        "C": [
            "▄▄▄▄",
            "█▄█ ",
            "█ █ ",
            "▀▀▀▀",
        ],
        "D": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █▄",
            "▀▀▀ ",
        ],
        "E": [
            "▄▄▄▄",
            "█▄█ ",
            "█ █ ",
            "▀▀▀▀",
        ],
        "F": [
            "▄▄▄▄",
            "█▄█ ",
            "█ █ ",
            "▀ ▀ ",
        ],
        "G": [
            "▄▄▄▄",
            "█▄█ ",
            "█ █▄",
            "▀▀▀▀",
        ],
        "H": [
            "▄ ▄ ",
            "█▄█▄",
            "█ █ ",
            "▀ ▀ ",
        ],
        "I": [
            "▄▄▄ ",
            " █  ",
            " █  ",
            "▀▀▀ ",
        ],
        "J": [
            "▄▄▄ ",
            "  █ ",
            "█ █ ",
            "▀▀▀ ",
        ],
        "K": [
            "▄ ▄ ",
            "█▄█ ",
            "█ █▄",
            "▀ ▀ ",
        ],
        "L": [
            "▄   ",
            "█   ",
            "█   ",
            "▀▀▀▀",
        ],
        "M": [
            "▄ ▄ ",
            "█▄█▄",
            "█ █ ",
            "▀ ▀ ",
        ],
        "N": [
            "▄ ▄ ",
            "█▄█▄",
            "█ █ ",
            "▀ ▀ ",
        ],
        "O": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █ ",
            "▀▀▀ ",
        ],
        "P": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █ ",
            "▀ ▀ ",
        ],
        "Q": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █▄",
            "▀▀▀▀",
        ],
        "R": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █ ",
            "▀ ▀▄",
        ],
        "S": [
            "▄▄▄▄",
            "█▄█ ",
            " █▄█",
            "▀▀▀▀",
        ],
        "T": [
            "▄▄▄▄",
            " █  ",
            " █  ",
            " ▀  ",
        ],
        "U": [
            "▄ ▄ ",
            "█ █ ",
            "█ █ ",
            "▀▀▀ ",
        ],
        "V": [
            "▄ ▄ ",
            "█ █ ",
            "█▄█ ",
            " ▀  ",
        ],
        "W": [
            "▄ ▄ ",
            "█ █ ",
            "█▄█▄",
            "▀ ▀ ",
        ],
        "X": [
            "▄ ▄ ",
            "█▄█ ",
            "█▄█ ",
            "▀ ▀ ",
        ],
        "Y": [
            "▄ ▄ ",
            "█▄█ ",
            " █  ",
            " ▀  ",
        ],
        "Z": [
            "▄▄▄▄",
            " ▄█ ",
            "█▄  ",
            "▀▀▀▀",
        ],
        "a": [
            "   ",
            "▄▄▄",
            "█▄█",
            "▀▀▀",
        ],
        "b": [
            "▄  ",
            "█▄▄",
            "█ █",
            "▀▀▀",
        ],
        "c": [
            "   ",
            "▄▄▄",
            "█  ",
            "▀▀▀",
        ],
        "d": [
            "  ▄",
            "▄▄█",
            "█ █",
            "▀▀▀",
        ],
        "e": [
            "   ",
            "▄▄▄",
            "█▄█",
            "▀▀▀",
        ],
        "f": [
            " ▄▄",
            "█▄ ",
            "█  ",
            "▀  ",
        ],
        "g": [
            "   ",
            "▄▄▄",
            "█ █",
            "▀▀█",
        ],
        "h": [
            "▄  ",
            "█▄▄",
            "█ █",
            "▀ ▀",
        ],
        "i": [
            "▄ ",
            "█ ",
            "█ ",
            "▀ ",
        ],
        "j": [
            " ▄ ",
            " █ ",
            "█ █",
            "▀▀ ",
        ],
        "k": [
            "▄  ",
            "█▄ ",
            "█ █",
            "▀ ▀",
        ],
        "l": [
            "▄ ",
            "█ ",
            "█ ",
            "▀ ",
        ],
        "m": [
            "    ",
            "▄▄▄▄",
            "█▄█▄",
            "▀ ▀ ",
        ],
        "n": [
            "   ",
            "▄▄▄",
            "█ █",
            "▀ ▀",
        ],
        "o": [
            "   ",
            "▄▄▄",
            "█ █",
            "▀▀▀",
        ],
        "p": [
            "   ",
            "▄▄▄",
            "█▄█",
            "▀  ",
        ],
        "q": [
            "   ",
            "▄▄▄",
            "█▄█",
            "  ▀",
        ],
        "r": [
            "   ",
            "▄▄▄",
            "█  ",
            "▀  ",
        ],
        "s": [
            "   ",
            "▄▄▄",
            "█▄ ",
            "▀▀▀",
        ],
        "t": [
            "▄  ",
            "█▄▄",
            "█  ",
            "▀  ",
        ],
        "u": [
            "   ",
            "▄ ▄",
            "█ █",
            "▀▀▀",
        ],
        "v": [
            "   ",
            "▄ ▄",
            "█▄█",
            " ▀ ",
        ],
        "w": [
            "    ",
            "▄ ▄ ",
            "█▄█▄",
            "▀ ▀ ",
        ],
        "x": [
            "   ",
            "▄ ▄",
            "█▄█",
            "▀ ▀",
        ],
        "y": [
            "   ",
            "▄ ▄",
            "█▄█",
            "  ▀",
        ],
        "z": [
            "   ",
            "▄▄▄",
            " ▄ ",
            "▀▀▀",
        ],
        "0": [
            "▄▄▄ ",
            "█▄█▄",
            "█ █ ",
            "▀▀▀ ",
        ],
        "1": [
            "▄▄ ",
            " █ ",
            " █ ",
            "▀▀▀",
        ],
        "2": [
            "▄▄▄ ",
            " ▄█ ",
            "█▄  ",
            "▀▀▀▀",
        ],
        "3": [
            "▄▄▄ ",
            " ▄█ ",
            " █▄ ",
            "▀▀▀ ",
        ],
        "4": [
            "▄ ▄ ",
            "█▄█▄",
            "  █ ",
            "  ▀ ",
        ],
        "5": [
            "▄▄▄▄",
            "█▄  ",
            " █▄█",
            "▀▀▀▀",
        ],
        "6": [
            "▄▄▄ ",
            "█▄  ",
            "█ █ ",
            "▀▀▀ ",
        ],
        "7": [
            "▄▄▄▄",
            "  █ ",
            " █  ",
            " ▀  ",
        ],
        "8": [
            "▄▄▄ ",
            "█▄█▄",
            "█▄█ ",
            "▀▀▀ ",
        ],
        "9": [
            "▄▄▄ ",
            "█ █ ",
            " █▄█",
            "▀▀▀ ",
        ],
        " ": [
            "   ",
            "   ",
            "   ",
            "   ",
        ],
        ".": [
            "  ",
            "  ",
            "▄ ",
            "▀ ",
        ],
        ",": [
            "  ",
            "  ",
            " ▄",
            "▄ ",
        ],
        "!": [
            "▄ ",
            "█ ",
            "█ ",
            "▀ ",
        ],
        "?": [
            "▄▄ ",
            " █ ",
            "   ",
            " ▀ ",
        ],
        "-": [
            "   ",
            "▄▄▄",
            "   ",
            "   ",
        ],
        "_": [
            "   ",
            "   ",
            "   ",
            "▀▀▀",
        ],
        "+": [
            "   ",
            " ▄ ",
            "▄█▄",
            " ▀ ",
        ],
        "=": [
            "   ",
            "▄▄▄",
            "▀▀▀",
            "   ",
        ],
        "/": [
            "  ▄",
            " ▄ ",
            "▄  ",
            "   ",
        ],
        "\\": [
            "▄  ",
            " ▄ ",
            "  ▄",
            "   ",
        ],
        ":": [
            "  ",
            "▄ ",
            "▄ ",
            "  ",
        ],
        ";": [
            "  ",
            "▄ ",
            " ▄",
            "▄ ",
        ],
        "(": [
            " ▄",
            "█ ",
            "█ ",
            "▀ ",
        ],
        ")": [
            "▄ ",
            " █",
            " █",
            " ▀",
        ],
        "[": [
            "▄▄",
            "█ ",
            "█ ",
            "▀▀",
        ],
        "]": [
            "▄▄",
            " █",
            " █",
            "▀▀",
        ],
        "{": [
            " ▄▄",
            "█  ",
            "█  ",
            "▀▀ ",
        ],
        "}": [
            "▄▄ ",
            "  █",
            "  █",
            " ▀▀",
        ],
        '"': [
            "▄ ▄",
            "█ █",
            "   ",
            "   ",
        ],
        "'": [
            "▄",
            "█",
            " ",
            " ",
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
            elif char.upper() in letter_art:
                line += letter_art[char.upper()][row]
            else:
                line += "   "
        art_lines.append(line)

    return art_lines


def create_banner_art(text, style="block"):
    if style == "block":
        return create_english_style_art(text)
    elif style == "bordered":
        art = create_english_style_art(text)
        if art:
            width = len(art[0])
            border_top = "▄" * (width + 4)
            border_bottom = "▀" * (width + 4)
            bordered_art = [border_top]
            for line in art:
                bordered_art.append("█ " + line + " █")
            bordered_art.append(border_bottom)
            return bordered_art
    return create_english_style_art(text)


def main():
    print("English Text Art Generator")
    print("=" * 50)
    print("Enter text to convert (English letters, numbers, and symbols)")
    print("Available commands:")
    print("  - Type 'quit' to exit")
    print("  - Type 'bordered' to toggle bordered style")
    print("  - Type 'clear' to clear screen")
    print()

    bordered = False

    while True:
        text = input("Enter text: ").strip()

        if text.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break
        elif text.lower() == "bordered":
            bordered = not bordered
            print(f"Bordered style: {'ON' if bordered else 'OFF'}")
            continue
        elif text.lower() == "clear":
            import os

            os.system("cls" if os.name == "nt" else "clear")
            continue

        if not text:
            print("Please enter some text.")
            continue

        if bordered:
            art = create_banner_art(text, "bordered")
        else:
            art = create_english_style_art(text)

        print("\n" + "=" * 50)
        for line in art:
            print(f'    "{line}",')
        print("=" * 50)
        print()


if __name__ == "__main__":
    main()
