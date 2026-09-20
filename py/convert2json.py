import json
import re


def parse_gitsources_file(input_file, output_file):
    results = []

    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            
            description_match = re.search(r"《([^》]+)》", line)
            if not description_match:
                continue
            description = description_match.group(1)

            
            url_match = re.search(r"GitHub:\s*(https?://[^\s]+)", line)
            if not url_match:
                continue
            url = url_match.group(1)

            results.append({"url": url, "description": description})

    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Successfully converted {len(results)} entries to {output_file}")


if __name__ == "__main__":
    parse_gitsources_file("gitsources.md", "git.json")
