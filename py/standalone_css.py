import base64
import os
import re
import requests


def get_file_extension(url):
    return os.path.splitext(url)[1].lower()


def is_font_url(url) -> bool:
    extensions = [".woff", ".woff2", ".ttf", ".eot", ".svg"]
    return any(url.lower().endswith(ext) for ext in extensions)


def url_to_base64(url) -> str | None:
    ext = look_local_font(url)
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0]
        if not content_type.startswith("font"):
            return None
        ext = get_file_extension(url)
        if ext == ".eot":
            content_type = "application/vnd.ms-fontobject"
        elif ext == ".ttf":
            content_type = "application/font-sfnt"
        elif ext == ".woff":
            content_type = "application/font-woff"
        elif ext == ".woff2":
            content_type = "font/woff2"
        elif ext == ".svg":
            content_type = "image/svg+xml"
        else:
            return None
        encoded_string = base64.b64encode(response.content).decode("utf-8")
        return f"data:{content_type};charset=utf-8;base64,{encoded_string}"
    except requests.exceptions.RequestException as e:
        print(f"Error fetching or encoding {url}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {url}: {e}")
        return None


def make_css_standalone(input_css_path, output_css_path) -> None:
    with open(input_css_path, "r", encoding="utf-8") as f:
        content = f.read()
    import_pattern = re.compile(r'@import\s+(?:url\()?(["\'])(.*?)\1\)?;', re.IGNORECASE)
    font_url_pattern = re.compile(r'url\((["\']?)([^)"\'\s]+?)\1?\)', re.IGNORECASE)
    processed_content = content
    import_urls_to_process = []
    for match in import_pattern.finditer(content):
        import_url = match.group(2)
        import_urls_to_process.append(import_url)
        processed_content = processed_content.replace(match.group(0), "", 1)
    while import_urls_to_process:
        current_url = import_urls_to_process.pop(0)
        print(f"Processing imported CSS: {current_url}")
        try:
            response = requests.get(current_url)
            response.raise_for_status()
            imported_css = response.text
            for sub_match in import_pattern.finditer(imported_css):
                sub_import_url = sub_match.group(2)
                if sub_import_url not in import_urls_to_process and sub_import_url not in current_url:
                    import_urls_to_process.append(sub_import_url)
                imported_css = imported_css.replace(sub_match.group(0), "", 1)
            processed_content += "\n/* Imported from: " + current_url + " */\n" + imported_css
        except requests.exceptions.RequestException as e:
            print(f"Could not import {current_url}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while processing {current_url}: {e}")

    def replace_font_urls(match):
        url = match.group(2)
        original_url_part = match.group(0)
        if not url.startswith(("http://", "https://", "//")):
            base_url = os.path.dirname(input_css_path)
            if not base_url:
                base_url = "."
            url = os.path.normpath(os.path.join(base_url, url))
            if not url.startswith(("http://", "https://")):
                url = f"file:///{os.path.abspath(url)}"
        if is_font_url(url):
            print(f"Found font URL: {url}")
            base64_data = url_to_base64(url)
            if base64_data:
                print(f"Successfully encoded {url}")
                return (
                    f'url("{base64_data}")'
                    if match.group(1) == '"'
                    else f"url('{base64_data}')"
                    if match.group(1) == "'"
                    else f"url({base64_data})"
                )
            else:
                print(f"Failed to encode font: {url}. Keeping original URL.")
                return original_url_part
        else:
            return original_url_part

    processed_content = font_url_pattern.sub(replace_font_urls, processed_content)
    with open(output_css_path, "w", encoding="utf-8") as f:
        f.write(processed_content)
    print(f"Standalone CSS file created at: {output_css_path}")


with open("main.css", "w") as f:
    f.write("""
@import "components.css";
body {
    font-family: 'Roboto', sans-serif;
    background-image: url('images/background.png'); /* Should be ignored */
}
h1 {
    font-family: url('fonts/awesome.woff2');
    color:
}
""")
with open("components.css", "w") as f:
    f.write("""
.button {
    padding: 10px 20px;
    background-color: blue;
    color: white;
    font-family: url("fonts/MaterialIcons-Regular.woff2"); /* Example with quotes */
}
@import url("https://fonts.googleapis.com/css2?family=Open+Sans&display=swap"); /* Example of external CSS import */
""")
