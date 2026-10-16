import asyncio
import hashlib
import re
import sys
from .processor import process_html_file


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m mdbookhtml2pdf <html file>")
        sys.exit(1)
    html_file = sys.argv[1]
    asyncio.run(process_html_file(html_file))


if __name__ == "__main__":
    main()
HIGHLIGHTJS_TO_PYGMENTS = {"gradle": "groovy", "bp": "blueprint", "sh": "shell"}


def _to_chinese_numeral(number: int) -> str:
    if number <= 0:
        return str(number)
    digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    unit_map = {3: "千", 2: "百", 1: "十", 0: ""}
    big_units = ["", "万", "亿", "兆"]

    def convert_section(section) -> str:
        if section == 0:
            return digits[0]
        result = []
        digit_seen = False
        remaining = section
        for power in range(3, -1, -1):
            divisor = 10**power
            digit = remaining // divisor
            if digit:
                result.append(digits[digit] + unit_map[power])
                digit_seen = True
            elif digit_seen and remaining % divisor and (not result or result[-1] != "零"):
                result.append("零")
            remaining %= divisor
        section_str = "".join(result).rstrip("零")
        if section_str.startswith("一十"):
            section_str = section_str[1:]
        return section_str or digits[0]

    sections = []
    while number > 0:
        sections.append(number % 10000)
        number //= 10000
    result_parts = []
    for idx in range(len(sections) - 1, -1, -1):
        section = sections[idx]
        if section == 0:
            if result_parts and result_parts[-1] != "零":
                lower_has_content = any((sections[i] != 0 for i in range(idx)))
                if lower_has_content:
                    result_parts.append("零")
            continue
        if result_parts and result_parts[-1] != "零" and (section < 1000) and (idx != len(sections) - 1):
            result_parts.append("零")
        section_text = convert_section(section)
        result_parts.append(section_text + big_units[idx])
    result = "".join(result_parts)
    if result.startswith("一十"):
        result = result[1:]
    return result or digits[0]


def _slugify(text) -> str:
    cleaned = re.sub("\\s+", "-", text.strip())
    cleaned = re.sub("[^0-9a-zA-Z\\- _]", "", cleaned).replace(" ", "-")
    cleaned = cleaned.lower().strip("-")
    if not cleaned:
        cleaned = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    return cleaned


def _ensure_heading_id(header, soup):
    if header.get("id"):
        return header["id"]
    base = _slugify(header.get_text(strip=True) or "section")
    candidate = base
    suffix = 1
    while soup.find(id=candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    header["id"] = candidate
    return candidate


def _collect_headings(content_div, soup):
    headings = []
    current_indices = [0] * 6
    for header in content_div.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = header.get_text(strip=True)
        if not text:
            continue
        heading_id = _ensure_heading_id(header, soup)
        level = int(header.name[1])
        current_indices[level - 1] += 1
        for idx in range(level, 6):
            current_indices[idx] = 0
        prefix = ".".join((str(i) for i in current_indices if i > 0))
        display_prefix = f"第{_to_chinese_numeral(current_indices[0])}章" if level == 1 else prefix
        headings.append({
            "tag": header,
            "level": level,
            "id": heading_id,
            "text": text,
            "prefix": prefix,
            "display_prefix": display_prefix,
        })
    return headings


def _build_nested_list(soup, items, base_class: str):
    if not items:
        return None
    root_ul = soup.new_tag("ul")
    root_ul["class"] = [base_class]
    stack = [(0, root_ul)]
    for item in items:
        level = item["level"]
        while stack and stack[-1][0] >= level:
            stack.pop()
        _parent_level, parent_ul = stack[-1]
        li = soup.new_tag("li")
        li["class"] = [f"{base_class}__item", f"level-{level}"]
        link = soup.new_tag("a")
        link["href"] = f"#{item['id']}"
        link["class"] = [f"{base_class}__link"]
        title = soup.new_tag("span")
        title["class"] = [f"{base_class}__title"]
        prefix = item.get("display_prefix", item["prefix"])
        title.string = f"{prefix} {item['text']}".strip()
        page = soup.new_tag("span")
        page["class"] = [f"{base_class}__page"]
        page["data-target"] = link["href"]
        link.append(title)
        link.append(page)
        li.append(link)
        parent_ul.append(li)
        child_ul = soup.new_tag("ul")
        child_ul["class"] = [base_class]
        li.append(child_ul)
        stack.append((level, child_ul))
    for child_ul in root_ul.find_all("ul"):
        if not child_ul.contents:
            child_ul.decompose()
    return root_ul


def _build_global_toc(soup, headings):
    toc_section = soup.new_tag("section")
    toc_section["id"] = "global-table-of-contents"
    title = soup.new_tag("div")
    title["class"] = ["toc-title"]
    title.string = "目录"
    toc_section.append(title)
    nav = soup.new_tag("nav")
    nav["id"] = "toc-global"
    nav["role"] = "doc-toc"
    toc_list = _build_nested_list(soup, headings, "toc-list")
    if toc_list:
        nav.append(toc_list)
    toc_section.append(nav)
    return toc_section


def _build_local_tocs(soup, headings) -> None:
    for existing in soup.select(".chapter-toc"):
        existing.decompose()
    for index, heading in enumerate(headings):
        if heading["level"] != 1:
            continue
        child_items = []
        probe = index + 1
        while probe < len(headings) and headings[probe]["level"] != 1:
            child_items.append(headings[probe])
            probe += 1
        if not child_items:
            continue
        chapter_toc = soup.new_tag("aside")
        chapter_toc["class"] = "chapter-toc"
        title = soup.new_tag("div")
        title["class"] = ["chapter-toc__title"]
        title.string = "本章目录"
        chapter_toc.append(title)
        toc_list = _build_nested_list(soup, child_items, "chapter-list")
        if toc_list:
            chapter_toc.append(toc_list)
            heading["tag"].insert_after(chapter_toc)


def _ensure_toc_styles(soup) -> None:
    if not soup.head:
        return
    style_tag = soup.find("style", attrs={"data-generator": "toc"})
    if not style_tag:
        style_tag = soup.new_tag("style")
        style_tag["data-generator"] = "toc"
        soup.head.append(style_tag)
    toc_style = "\n/* ==================== 页面分页样式 ==================== */\nh2,\nh3,\nh4,\nh5,\nh6 {\n  page-break-before: always;\n  page-break-after: avoid;\n}\n/* ==================== 全局目录容器 ==================== */\n  break-before: page;\n  page: no-chapter;\n  padding: 2cm 0 1cm;\n  background: linear-gradient(135deg,\n  border-radius: 12px;\n  margin: 1cm 0;\n  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);\n  page-break-after: always;\n}\n/* 目录标题 */\n.toc-title {\n  font-size: 26pt;\n  font-weight: 700;\n  letter-spacing: 0.1em;\n  text-transform: uppercase;\n  margin-bottom: 1.8cm;\n  text-align: center;\n  color:\n  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);\n  position: relative;\n  padding: 1em 0;\n}\n.toc-title::after {\n  content: '';\n  position: absolute;\n  bottom: -0.5cm;\n  left: 50%;\n  transform: translateX(-50%);\n  width: 80px;\n  height: 3px;\n  background: linear-gradient(90deg,\n  border-radius: 2px;\n}\n/* ==================== 全局目录导航 ==================== */\n  background: rgba(255, 255, 255, 0.95);\n  border-radius: 8px;\n  padding: 2em 2.5em;\n  margin: 0 1cm;\n  backdrop-filter: blur(10px);\n  border: 1px solid rgba(255, 255, 255, 0.2);\n  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);\n}\n/* 目录列表基础样式 */\n  list-style: none;\n  margin: 0;\n  padding: 0;\n}\n/* 嵌套列表样式 */\n  list-style: none;\n  margin: 0.5em 0 0.5em 1.2em;\n  padding-left: 1.2em;\n  border-left: 2px solid\n  position: relative;\n}\n  content: '';\n  position: absolute;\n  left: -2px;\n  top: 0;\n  bottom: 0;\n  width: 2px;\n  background: linear-gradient(180deg,\n  border-radius: 1px;\n}\n/* 目录项样式 */\n  margin: 0.5em 0;\n  position: relative;\n  transition: all 0.3s ease;\n}\n  margin-top: 1em;\n  margin-bottom: 1.2em;\n}\n  content: '';\n  position: absolute;\n  left: -1.2em;\n  top: 50%;\n  transform: translateY(-50%);\n  width: 8px;\n  height: 8px;\n  background:\n  border-radius: 50%;\n  box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.1);\n}\n/* 目录链接样式 */\n  color:\n  text-decoration: none;\n  display: flex;\n  justify-content: space-between;\n  align-items: baseline;\n  gap: 1.5em;\n  font-weight: 500;\n  padding: 0.4em 0.6em;\n  border-radius: 6px;\n  transition: all 0.3s ease;\n  position: relative;\n}\n  background: rgba(102, 126, 234, 0.1);\n  color:\n  transform: translateX(2px);\n}\n/* 目录标题样式 */\n  flex: 1;\n  position: relative;\n  padding-right: 1.5em;\n  font-variant-numeric: tabular-nums;\n}\n  content: leader('.');\n  color: rgba(102, 126, 234, 0.8);\n  margin-left: 0.5em;\n}\n/* 页码样式 */\n  min-width: 2em;\n  text-align: right;\n  font-weight: 600;\n  color:\n  font-variant-numeric: tabular-nums;\n  background: rgba(102, 126, 234, 0.12);\n  padding: 0.2em 0.5em;\n  border-radius: 12px;\n}\n  content: target-counter(attr(data-target), page);\n}\n/* ==================== 章节目录样式 ==================== */\n.chapter-toc {\n  background: linear-gradient(135deg,\n  border-radius: 8px;\n  margin: 1.5em 0 2.5em;\n  padding: 0;\n  overflow: hidden;\n  box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);\n  position: relative;\n  page-break-after: always;\n}\n.chapter-toc::before {\n  content: '';\n  position: absolute;\n  top: 0;\n  left: 0;\n  right: 0;\n  height: 3px;\n  background: linear-gradient(90deg,\n}\n/* 章节目录标题 */\n.chapter-toc__title {\n  color:\n  font-size: 12pt;\n  font-weight: 700;\n  letter-spacing: 0.1em;\n  text-transform: uppercase;\n  margin-bottom: 0;\n  padding: 1em 1.4em;\n  background: rgba(255, 255, 255, 0.1);\n  backdrop-filter: blur(10px);\n  position: relative;\n}\n.chapter-toc__title::after {\n  content: '';\n  position: absolute;\n  bottom: 0;\n  left: 1.4em;\n  right: 1.4em;\n  height: 1px;\n  background: rgba(255, 255, 255, 0.2);\n}\n/* 章节目录列表 */\n.chapter-toc .chapter-list {\n  background: rgba(255, 255, 255, 0.95);\n  margin: 0;\n  padding: 1.2em 1.4em;\n  backdrop-filter: blur(10px);\n}\n.chapter-toc .chapter-list ul {\n  list-style: none;\n  margin: 0.3em 0 0.3em 1em;\n  padding-left: 1em;\n  border-left: 2px solid\n  position: relative;\n}\n/* 章节目录链接 */\n.chapter-toc .chapter-list__link {\n  display: flex;\n  justify-content: space-between;\n  align-items: baseline;\n  text-decoration: none;\n  color:\n  font-size: 10pt;\n  padding: 0.3em 0;\n  border-radius: 4px;\n  transition: all 0.3s ease;\n}\n.chapter-toc .chapter-list__link:hover {\n  background: rgba(52, 152, 219, 0.1);\n  color:\n  transform: translateX(2px);\n}\n/* 章节目录标题 */\n.chapter-toc .chapter-list__title {\n  flex: 1;\n  position: relative;\n  padding-right: 1.2em;\n}\n.chapter-toc .chapter-list__title::after {\n  content: leader('.');\n  margin-left: 0.3em;\n  color: rgba(10, 132, 255, 0.35);\n}\n/* 章节目录页码 */\n.chapter-toc .chapter-list__page {\n  min-width: 1.6em;\n  text-align: right;\n  font-weight: 600;\n  color:\n  font-variant-numeric: tabular-nums;\n}\n.chapter-toc .chapter-list__page::before {\n  content: target-counter(attr(data-target), page);\n}\n/* ==================== 响应式设计 ==================== */\n@media (max-width: 768px) {\n    margin: 0.5cm;\n    padding: 1.5cm 0 0.8cm;\n  }\n    margin: 0;\n    padding: 1.5em;\n  }\n  .chapter-toc {\n    margin: 1em 0;\n  }\n}\n"
    style_tag.string = toc_style
