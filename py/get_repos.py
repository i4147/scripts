from github import Github

from github import Auth
from dotenv import load_dotenv
from os import getenv

load_dotenv()
token = getenv("GITHUB_TOKEN")
auth = Auth.Token(token)


g = Github(auth=auth)

g = Github(base_url="https://github.com/api/v3", auth=auth)

for repo in g.get_user().get_repos():
    print(repo.name)

g.close()
