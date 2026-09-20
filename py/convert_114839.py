import json
import re


def parse_gitsources_file(input_file, output_file):
    results = []
    remaining_lines = []
    parsed_count = 0

    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        original_line = line
        line = line.strip()

        if not line:
            remaining_lines.append(original_line)
            continue

        
        description_match = re.search(r"《([^》]+)》", line)
        if not description_match:
            remaining_lines.append(original_line)
            continue

        
        url_match = re.search(r"GitHub:\s*(https?://[^\s]+)", line)
        if not url_match:
            remaining_lines.append(original_line)
            continue

        
        description = description_match.group(1)
        url = url_match.group(1)

        results.append({"url": url, "description": description})
        parsed_count += 1
        

    
    with open(input_file, "w", encoding="utf-8") as f:
        f.writelines(remaining_lines)

    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Successfully parsed {parsed_count} entries")
    print(f"Remaining lines in {input_file}: {len(remaining_lines)}")
    print(f"JSON saved to {output_file}")


if __name__ == "__main__":
    parse_gitsources_file("gitsources.md", "git.json")
