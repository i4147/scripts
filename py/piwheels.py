import requests

url = "https://www.piwheels.org/project/{pkg}/json"
package = requests.get(url).json()
for version, release in package["releases"].items():
    print(version, release["released"])
for version, info in package["releases"].items():
    if info["files"]:
        print("{}: {} files".format(version, len(info["files"])))
    else:
        print(f"{version}: No files")
