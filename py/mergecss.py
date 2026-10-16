from dh import runcmd

if __name__ == "__main__":
    cmd = ["cleancss", "-O2", "removeDuplicateRules:on", "*.css", "-o", "merged.css"]
    runcmd(cmd, show_output=True)
