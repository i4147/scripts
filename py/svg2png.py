import subprocess
import xml.etree.ElementTree as ET


def svg2png(inputfile) -> None:
    try:
        ET.parse(inputfile)
    except ET.ParseError:
        raise ValueError("The file isn't a valid SVG")
    try:
        subprocess.check_call(["inkscape", "--export-type=png", inputfile])
    except:
        raise ValueError("Inkscape is not installed or not in the PATH")
