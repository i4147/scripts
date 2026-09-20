import json
import re
import sys
from pathlib import Path

DEFAULT_FILE = "README.md"


def parse_api_keys_from_table(text: str):
    lines = text.strip().split("\n")
    header_line = None
    data_start = 0
    for i, line in enumerate(lines):
        if "| Key | Model |" in line or ("Key" in line and "Model" in line):
            header_line = i
            data_start = i + 2
            break
    if header_line is None:
        data_start = 0
    pattern = r"\|\s*`([^`]+)`\s*\|\s*([^\s|]+)\s*\|"
    pattern = "\\|\\s*`([^`]+)`\\s*\\|\\s*([^\\s|]+)\\s*\\|"
    cleaned_name = ""
    env_vars = {}
    model_list = []
    for line in lines[data_start:]:
        if not line.strip() or line.strip().startswith("|--"):
            continue
        match = re.search(pattern, line)
        if match:
            api_key = match.group(1)
            model = match.group(2).lower()
            model_list.append(model)
            if "deepseek" in model:
                env_vars["DEEPSEEK_TOKEN"] = api_key
            elif "gemini" in model:
                env_vars["GEMINI_TOKEN"] = api_key
            elif "openai" in model or "gpt" in model:
                env_vars["OPENAI_TOKEN"] = api_key
            elif "claude" in model or "anthropic" in model:
                env_vars["ANTHROPIC_TOKEN"] = api_key
            else:
                model_upper = model.upper().replace("-", "_")
                if "/" in model_upper:
                    indx = model_upper.index("/")
                    cleaned_name = model_upper[:indx]
                env_vars[f"{cleaned_name}_TOKEN"] = api_key
    with open("model_list", "w") as f:
        json.dump(model_list, f, ensure_ascii=False, indent=2)
    return env_vars


def write_env_file(env_vars, output_file=".env"):
    env_path = Path(output_file)
    existing_vars = {}
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and (not line.startswith("#")) and ("=" in line):
                    key = line.split("=")[0]
                    if not key.endswith("_TOKEN") and key != "TOKEN":
                        existing_vars[key] = line
    with open(env_path, "w") as f:
        for key, value in existing_vars.items():
            f.write(f"{value}\n")
        if existing_vars:
            f.write("\n")
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
    print(f"✅ Wrote {len(env_vars)} token(s) to {output_file}")
    return env_vars


def main() -> None:
    if len(sys.argv) > 1:
        fn = Path(sys.argv[1])
    else:
        fn = Path(DEFAULT_FILE)
    table_data = fn.read_text(encoding="utf-8")
    env_vars = parse_api_keys_from_table(table_data)
    if env_vars:
        write_env_file(env_vars)
        print("\n📋 Extracted tokens:")
        for key, value in env_vars.items():
            masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
            print(f"  {key}={masked}")
    else:
        print("❌ No API keys found in the input")
        print("Expected format: | `api-key-here` | model-name | ...")


if __name__ == "__main__":
    main()
