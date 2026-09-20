import sys


def main() -> None:
    filename = sys.argv[1]
    if filename.lower().endswith(".png"):
        try:
            import cv2

            img = cv2.imread(filename)
            if img is not None:
                jpg_filename = filename[:-4] + ".jpg"
                cv2.imwrite(jpg_filename, img)
                print(f"Converted {filename} to {jpg_filename} using OpenCV.")
                os.remove(filename)
            else:
                msg = "OpenCV failed to read the image."
                raise Exception(msg)
        except:
            try:
                from PIL import Image

                img = Image.open(filename)
                jpg_filename = filename[:-4] + ".jpg"
                img.convert("RGB").save(jpg_filename, "JPEG")
                print(f"Converted {filename} to {jpg_filename} using Pillow.")
                os.remove(filename)
            except Exception as e:
                print(f"Failed to convert {filename}: {e}")
    else:
        print(f"{filename} is not a PNG file.")


if __name__ == "__main__":
    main()
