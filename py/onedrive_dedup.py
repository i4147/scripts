import hashlib
import requests

ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0/me/drive/root/children"


def get_file_hash(content):
    sha = hashlib.sha256()
    sha.update(content)
    return sha.hexdigest()


def list_files():
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(GRAPH_ROOT, headers=headers)
    response.raise_for_status()
    return response.json().get("value", [])


def download_file(file_id):
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/content"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.content


def delete_file(file_id):
    url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.delete(url, headers=headers)
    if response.status_code in (200, 204):
        print(f"Deleted duplicate: {file_id}")
    else:
        print(f"Failed to delete {file_id}: {response.text}")


def dedup_onedrive():
    files = list_files()
    seen_hashes = {}

    for f in files:
        file_id = f["id"]
        name = f["name"]

        print(f"Processing {name}...")

        try:
            content = download_file(file_id)
            file_hash = get_file_hash(content)

            if file_hash in seen_hashes:
                print(f"Duplicate found: {name} matches {seen_hashes[file_hash]}")
                delete_file(file_id)
            else:
                seen_hashes[file_hash] = name

        except Exception as e:
            print(f"Error processing {name}: {e}")


if __name__ == "__main__":
    dedup_onedrive()
