import os
import requests
from dotenv import load_dotenv

load_dotenv()


def create_github_repo(repo_name, description: str = "", private: bool = False):
    token = os.getenv("GITHUB_TOKEN")

    if not token:
        raise ValueError("GITHUB_TOKEN not found in .env file")

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    data = {"name": repo_name, "description": description, "private": private, "auto_init": True}

    response = requests.post("https://api.github.com/user/repos", json=data, headers=headers)

    if response.status_code == 201:
        return response.json()["html_url"]
    else:
        raise Exception(f"GitHub API error: {response.json().get('message')}")



try:
    repo_url = create_github_repo(repo_name="my-awesome-project", description="Created with Python!", private=False)
    print(f"✅ Repo created: {repo_url}")
except Exception as e:
    print(f"❌ Error: {e}")
