import json
import re


def preprocess_lines():
    lines = []
    content = ""
    with open("gitsources.md", encoding="utf-8") as f:
        content = f.read()
    lines = content.splitlines()
    print(len(lines))
    processed_lines = []
    current_line = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        
        if line.startswith("《"):
            
            if current_line:
                processed_lines.append(current_line)
            
            current_line = line
        else:
            
            if current_line:
                current_line += line
            else:
                
                current_line = line

    
    if current_line:
        processed_lines.append(current_line)

    
    fixed_lines = []
    for line in processed_lines:
        
        line = re.sub(r"Github:\s*github\.com", "Github: https://github.com", line, flags=re.IGNORECASE)

        
        line = re.sub(r"https://\s*githhub\.com", "https://github.com", line, flags=re.IGNORECASE)

        fixed_lines.append(line)
    with open("gh2.md", "w") as fo:
        for k in fixed_lines:
            fo.write(f"{k}\n")
    return fixed_lines


def process_file(input_file, output_file):
    results = []
    remaining_lines = []
    parsed_count = 0

    with open(input_file, "r", encoding="utf-8") as f:
        original_lines = f.readlines()

    
    print("Preprocessing source file...")

    
    for line in original_lines:
        original_line = line
        line = line.strip()

        if not line:
            continue

        
        description_match = re.search(r"《([^》]+)》", line)
        if not description_match:
            remaining_lines.append(original_line)
            continue

        
        url_match = re.search(r"Github?:\s*(https?://[^\s]+)", line, re.IGNORECASE)
        if not url_match:
            remaining_lines.append(original_line)
            continue

        
        description = description_match.group(1)
        url = url_match.group(1)

        results.append({"url": url, "description": description})
        parsed_count += 1

    
    with open(input_file, "w", encoding="utf-8") as f:
        f.write("\n".join(remaining_lines))
        if remaining_lines:
            f.write("\n")  

    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"Successfully parsed {parsed_count} entries")
    print(f"Remaining lines in {input_file}: {len(remaining_lines)}")
    print(f"JSON saved to {output_file}")


if __name__ == "__main__":
    process_file("gh2.md", "gh3.json")
