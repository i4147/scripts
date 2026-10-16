def rm_doc(content: str) -> tuple[str, int]:
    removed_count = 0
    lines = content.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if DOC_TH1 in line or DOC_TH2 in line:
            delimiter = DOC_TH1 if DOC_TH1 in line else DOC_TH2
            count = line.count(delimiter)
            if count >= 2:
                first = line.find(delimiter)
                second = line.find(delimiter, first + 3)
                before = line[:first].rstrip()
                if before.endswith(":") or before.strip() == "":
                    result_lines.append(line[:first] + line[second + 3 :])
                    removed_count += 1
                    i += 1
                    continue
            before = line[: line.find(delimiter)].rstrip()
            if before.endswith(":") or before.strip() == "" or "=" not in before:
                removed_count += 1
                if before:
                    result_lines.append(before)
                j = i + 1
                while j < len(lines):
                    if delimiter in lines[j]:
                        after = lines[j][lines[j].find(delimiter) + 3 :].strip()
                        if after:
                            result_lines.append(after)
                        i = j + 1
                        break
                    j += 1
                else:
                    i = j
            else:
                result_lines.append(line)
                i += 1
        else:
            result_lines.append(line)
            i += 1
    return "\n".join(result_lines), removed_count
