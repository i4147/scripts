import rignore

lic = {
    "# Copyright 2015 Google Inc. All Rights Reserved.",
    "# you may not use this file except in compliance with the License.",
    '# Licensed under the Apache License, Version 2.0 (the "License");',
    "# You may obtain a copy of the License at",
    "#     http://www.apache.org/licenses/LICENSE-2.0",
    "# Unless required by applicable law or agreed to in writing, software",
    '# distributed under the License is distributed on an "AS IS" BASIS,',
    "# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "# See the License for the specific language governing permissions and",
    "# limitations under the License.",
}


def process_file(fp) -> bool:
    new_lines = []
    lines = []
    with open(fp, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
        for line in lines:
            if line.strip() not in lic:
                new_lines.append(line)
    if len(new_lines) != len(lines):
        with open(fp, "w") as fo:
            for k in new_lines:
                fo.write(k)
        return True
    else:
        return False


def main() -> int:
    for pth in rignore.walk("/data/data/com.termux/files/usr/lib/python3.12/site-packages/yapf"):
        if pth.is_file() and pth.suffix == ".py" and process_file(pth):
            print(f"{pth.name}")
    return 0


if __name__ == "__main__":
    main()
