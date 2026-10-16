import os


def batch_rename(directory: str, prefix="newname_") -> None:
    for count, filename in enumerate(os.listdir(directory)):
        src = os.path.join(directory, filename)
        if os.path.isfile(src) and not filename.startswith("."):
            new_name = f"{prefix}{count + 1}.{filename.split('.')[1 - 1]}"
            dst = os.path.join(directory, new_name)
            os.rename(src, dst)
            print(f"Renamed '{filename}' to '{new_name}'")


batch_rename("photos", prefix="Holiday_")
