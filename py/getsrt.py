import subprocess
import sys
from pathlib import Path


def extract_subtitles(path):
    if not path.exists():
        return
    output_path = path.with_suffix(".srt")
    cmd = ["ffmpeg", "-i", str(path), "-map", "0:s:0", "-y", str(output_path)]
    try:
        subprocess.run(cmd, check=True)
    except:
        print("Error")


if __name__ == "__main__":
    fn = Path(sys.argv[1].strip())
    extract_subtitles(fn)
