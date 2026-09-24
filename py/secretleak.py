from __future__ import annotations

import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SECRET_PATTERNS = {
    "AWS Key": "AKIA[0-9A-Z]{16}",
    "Private Key": "-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----",
    "GitHub Token": "ghp_[A-Za-z0-9_]{36,255}",
    "Generic API Key": "api[_-]?key['\\\"]?\\s*[:=]\\s*['\\\"]?[A-Za-z0-9\\-_]{20,}",
    "Database URL": "(?:mysql|postgresql|mongodb)://[^\\s]+",
    "Slack Token": "xox[baprs]-[0-9]{10,13}-[0-9]{10,13}[A-Za-z0-9-]*",
    "Generic Password": "password['\\\"]?\\s*[:=]\\s*['\\\"]?[A-Za-z0-9\\-_!@#$%]{8,}",
    "AWS Secret": "aws_secret_access_key['\\\"]?\\s*[:=]\\s*['\\\"]?[A-Za-z0-9/+=]{40}",
    "Google API Key": "AIza[0-9A-Za-z\\-_]{35}",
    "JWT Token": "eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+",
}
SKIP_EXTENSIONS = {
    ".pyc",
    ".so",
    ".o",
    ".a",
    ".exe",
    ".dll",
    ".dylib",
    ".jpg",
    ".png",
    ".gif",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".git",
    ".svg",
    ".lock",
    ".bin",
    ".class",
}
SKIP_PATTERNS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".env.example"}


def should_skip_file(file_path: Path) -> bool:
    if file_path.suffix.lower() in SKIP_EXTENSIONS:
        return True
    for pattern in SKIP_PATTERNS:
        if pattern in file_path.parts:
            return True
    return bool(file_path.is_symlink())


def scan_file(file_path: Path) -> tuple[str, list[dict]]:
    leaks = []
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return str(file_path), leaks
    for secret_name, pattern in SECRET_PATTERNS.items():
        matches = re.finditer(pattern, content, re.IGNORECASE)
        for match in matches:
            line_num = content[: match.start()].count("\n") + 1
            lines = content.split("\n")
            line_content = lines[line_num - 1] if line_num <= len(lines) else ""
            leaks.append(
                {
                    "secret_type": secret_name,
                    "line_number": line_num,
                    "matched_text": match.group(0)[:50] + "..." if len(match.group(0)) > 50 else match.group(0),
                    "line_content": line_content[:80] + "..." if len(line_content) > 80 else line_content,
                }
            )
    return str(file_path), leaks


def get_all_files(root_dir: Path = Path(".")) -> list[Path]:
    files = []
    try:
        for path in root_dir.rglob("*"):
            if path.is_file() and not should_skip_file(path):
                files.append(path)
    except PermissionError:
        pass
    return files


def check_secrets(root_dir: Path = Path("."), max_workers: int | None = None) -> tuple[int, int]:
    files = get_all_files(root_dir)
    if not files:
        print("No files found to scan.")
        return 0, 0
    print(f"Scanning {len(files)} files for secrets...\n")
    total_leaks = 0
    files_with_leaks = 0
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(scan_file, file): file for file in files}
        for future in as_completed(future_to_file):
            file_path, leaks = future.result()
            if leaks:
                files_with_leaks += 1
                print(f"⚠️  Found {len(leaks)} secret(s) in: {file_path}")
                for leak in leaks:
                    print(f"   - {leak['secret_type']} at line {leak['line_number']}")
                    print(f"     Matched: {leak['matched_text']}")
                    print(f"     Content: {leak['line_content']}\n")
                total_leaks += len(leaks)
    return len(files), total_leaks, files_with_leaks


def main():
    print("-" * 40)
    print("SECRET LEAK DETECTOR - Pre-GitHub Push Scanner")
    print("-" * 40)
    print()
    try:
        total_files, total_leaks, files_affected = check_secrets()
        print("-" * 40)
        print("Scan Complete!")
        print(f"Files scanned: {total_files}")
        print(f"Leaks found: {total_leaks}")
        print(f"Files with leaks: {files_affected}")
        print("-" * 40)
        if total_leaks > 0:
            print("\n❌ SECRETS DETECTED! DO NOT PUSH TO GITHUB!")
            print("Please review and remove the secrets before committing.\n")
            return 1
        else:
            print("\n✅ No secrets detected. Safe to push!\n")
            return 0
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        return 2
    except Exception as e:
        print(f"\n❌ Error during scan: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
