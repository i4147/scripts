import re


def extract_names_from_md(input_file="models.md", output_file="extracted_names.txt"):
    try:
        with open(input_file, "r", encoding="utf-8") as file:
            content = file.read()

        pattern = r"\[([^\]]+)\]"
        names = re.findall(pattern, content)

        seen = set()
        unique_names = []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique_names.append(name)

        with open(output_file, "w", encoding="utf-8") as file:
            for name in unique_names:
                file.write(name + "\n")

        print(f"Successfully extracted {len(unique_names)} names!")
        print(f"Names saved to: {output_file}")

        print("\nExtracted names:")
        for name in unique_names:
            print(f"- {name}")

    except FileNotFoundError:
        print(f"Error: {input_file} not found in the current directory.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    extract_names_from_md()
