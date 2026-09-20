import os
import pickle as pk


def main() -> None:
    data = {}
    for file in os.listdir("."):
        if file.endswith(".pickle"):
            with open(file, "rb") as f:
                data = pk.load(f)
                print(data)
            newfile = file.replace(".pickle", ".json")
            with open(newfile, "w") as fo:
                fo.write(str(data))


if __name__ == "__main__":
    main()
