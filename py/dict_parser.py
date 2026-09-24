import sys
import json
import re
import html
from html.parser import HTMLParser

PAGE_MARKER = re.compile(r"<!\s*p\.\s*(\d+)\s*!>")


class WebsterParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.reset_entry()
        self.entries = []
        self.tag_stack = []

    def reset_entry(self):
        self.entry = {
            "word": "",
            "pronunciation": "",
            "part_of_speech": "",
            "etymology": "",
            "senses": [],
            "collocations": [],
            "synonyms": "",
            "notes": [],
            "quotes": [],
            "page": None,
        }
        self.current_sense = None
        self.current_quote = None
        self.current_collocation = None
        self.in_etymology = False
        self.in_pos = False
        self.in_hw = False
        self.in_def = False
        self.in_sn = False
        self.in_plw = False
        self.in_u = False
        self.in_grk = False
        self.buf = []

    def _flush_buffer(self):
        text = "".join(self.buf)
        self.buf = []
        return text

    def _append(self, text):
        if not text:
            return

        if self.current_collocation is not None:
            self.current_collocation["definition"] += text
            return

        if self.current_sense is not None:
            self.current_sense["text"] += text
            return

        if self.in_hw:
            self.entry["word"] += text
        elif self.in_pos:
            self.entry["part_of_speech"] += text
        elif self.in_etymology:
            self.entry["etymology"] += text
        elif self.in_def:
            self.entry["definition_raw"] = self.entry.get("definition_raw", "") + text
        elif self.in_sn:
            if self.current_sense is None:
                num = text.strip().rstrip(".")
                self.current_sense = {"number": num, "text": "", "quotes": []}
            else:
                self.current_sense["text"] += text
        elif self.current_quote is not None:
            self.current_quote["text"] += text
        else:
            pass

    def handle_starttag(self, tag, attrs):
        self.tag_stack.append(tag)

        if tag == "hw":
            self.in_hw = True
        elif tag == "pos":
            self.in_pos = True
        elif tag == "def":
            self.in_def = True
        elif tag == "sn":
            self.in_sn = True
        elif tag == "plw":
            self.in_plw = True
        elif tag == "u":
            self.in_u = True
        elif tag == "grk":
            self.in_grk = True
        elif tag == "blockquote":
            self.current_quote = {"text": "", "source": ""}
        elif tag == "col":
            self.current_collocation = {"phrase": "", "definition": ""}
        elif tag == "cd":
            pass
        elif tag == "i":
            if self.in_etymology:
                pass
        elif tag == "br":
            self._append("\n")

    def handle_endtag(self, tag):
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()

        if tag == "hw":
            self.in_hw = False
        elif tag == "pos":
            self.in_pos = False
        elif tag == "def":
            self.in_def = False
        elif tag == "sn":
            self.in_sn = False

        elif tag == "plw":
            self.in_plw = False
        elif tag == "u":
            self.in_u = False
        elif tag == "grk":
            self.in_grk = False
        elif tag == "blockquote":
            if self.current_quote:
                self.current_quote["text"] = " ".join(self.current_quote["text"].split())
                self.entry["quotes"].append(self.current_quote)
                if self.current_sense is not None:
                    self.current_sense["quotes"].append(self.current_quote)
            self.current_quote = None
        elif tag == "col":
            if self.current_collocation and self.current_collocation["phrase"]:
                self.current_collocation["phrase"] = " ".join(self.current_collocation["phrase"].split())
                self.current_collocation["definition"] = " ".join(self.current_collocation["definition"].split())
                self.entry["collocations"].append(self.current_collocation)
            self.current_collocation = None
        elif tag == "cd":
            pass

    def handle_data(self, data):
        text = data

        if "i" in self.tag_stack and not self.current_sense and self.current_collocation is None:
            if self.current_quote is not None:
                self.current_quote["source"] += text
                return

            if self.in_def:
                self._append(text)
                return

            if not self.in_hw and not self.in_pos and not self.in_def:
                self.in_etymology = True
                self.entry["etymology"] += text
                return

        if self.current_collocation is not None and "col" in self.tag_stack:
            self.current_collocation["phrase"] += text
            return

        if self.current_quote is not None:
            self.current_quote["text"] += text
            return

        if self.in_sn:
            self._append(text)
            return

        self._append(text)

    def finish(self):
        entry = self.entry

        if not entry["senses"] and entry.get("definition_raw"):
            entry["senses"].append(
                {
                    "number": "1",
                    "text": " ".join(entry.pop("definition_raw").split()),
                    "quotes": entry["quotes"],
                }
            )
        elif entry["definition_raw"]:
            entry["senses"].append(
                {
                    "number": None,
                    "text": " ".join(entry.pop("definition_raw").split()),
                    "quotes": [],
                }
            )
        entry.pop("definition_raw", None)

        if self.current_sense is not None:
            self.current_sense["text"] = " ".join(self.current_sense["text"].split())
            if self.current_sense["text"] or self.current_sense["quotes"]:
                entry["senses"].append(self.current_sense)
            self.current_sense = None

        for key in ("word", "pronunciation", "part_of_speech", "etymology", "synonyms"):
            if key in entry and isinstance(entry[key], str):
                entry[key] = " ".join(entry[key].split())

        for s in entry["senses"]:
            s["text"] = " ".join(s["text"].split())
            for q in s.get("quotes", []):
                q["text"] = " ".join(q["text"].split())
                q["source"] = " ".join(q["source"].split())

        if entry["word"]:
            self.entries.append(entry)

        self.reset_entry()


def parse_file(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    parts = []
    last = 0
    current_page = None
    for m in PAGE_MARKER.finditer(raw):
        parts.append((current_page, raw[last : m.start()]))
        current_page = int(m.group(1))
        last = m.end()
    parts.append((current_page, raw[last:]))

    entries = []
    for page, chunk in parts:
        for p_match in re.finditer(r"<p>(.*?)</p>", chunk, re.DOTALL):
            body = p_match.group(1).strip()

            if not body or re.fullmatch(r"<!\s*.*?\s*!>", body):
                continue

            parser = WebsterParser()
            parser.feed("<p>" + body + "</p>")
            parser.finish()
            for e in parser.entries:
                e["page"] = page
                entries.append(e)

    return entries


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <input_file>")
        sys.exit(1)

    entries = parse_file(sys.argv[1])
    out = sys.argv[1].rsplit(".", 1)[0] + ".json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(entries)} entries to {out}")
    if entries:
        for e in entries:
            if e["word"]:
                print("\nSample:")
                print(json.dumps(e, indent=2, ensure_ascii=False))
                break


if __name__ == "__main__":
    main()
