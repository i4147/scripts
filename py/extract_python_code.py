import pathlib
import regexrs as re


def extract_python_code(input_file: str) -> None:
    output_file = "extracted_code.py"
    code_pattern = re.compile(r"^\s*\d+\s*\|\s*(.*)")
    try:
        with pathlib.Path(input_file).open("r", encoding="utf-8") as f_in:
            lines = f_in.readlines()
        extracted = []
        remain = []
        for line in lines:
            match = code_pattern.search(line)
            if match:
                extracted.append(match.group(1))
            else:
                remain.append(line)
        if extracted:
            pathlib.Path(output_file).write_text(
                "\n".join(extracted),
                encoding="utf-8",
            )
            print(f"Success! {len(extracted)} code lines saved to {output_file}")
        else:
            print("No matching code lines found.")
        with pathlib.Path("20.txt").open("w", encoding="utf-8") as fio:
            for x in remain:
                if not (x.lower().startswith("plr091") or "[39m" in x):
                    fio.write(x)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    extract_python_code("20.txt")
