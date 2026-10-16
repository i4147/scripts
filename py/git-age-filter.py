import os
import subprocess
import sys

AGE_BIN = os.path.expanduser("~/../usr/bin/age")
if not os.path.exists(AGE_BIN):
    AGE_BIN = "age"
AGE_KEY_FILE = os.path.expanduser("~/.config/age/keys.txt")
AGE_PUBKEY_FILE = os.path.expanduser("~/.config/age/public.key")


def die(msg, code=1):
    print(f"git-age-filter: {msg}", file=sys.stderr)
    sys.exit(code)


def clean():
    if not os.path.exists(AGE_PUBKEY_FILE):
        die(f"missing public key file: {AGE_PUBKEY_FILE}")
    pubkey = open(AGE_PUBKEY_FILE).read().strip()
    if not pubkey:
        die("public key file is empty")
    proc = subprocess.run(
        [AGE_BIN, "-r", pubkey, "-a"],
        input=sys.stdin.buffer.read(),
        capture_output=True,
    )
    if proc.returncode != 0:
        die(f"age encrypt failed: {proc.stderr.decode(errors='replace')}")
    sys.stdout.buffer.write(proc.stdout)


def smudge():
    data = sys.stdin.buffer.read()
    if not data.lstrip().startswith(b"-----BEGIN AGE ENCRYPTED FILE-----"):
        sys.stdout.buffer.write(data)
        return
    if not os.path.exists(AGE_KEY_FILE):
        print("git-age-filter: no private key; leaving ciphertext", file=sys.stderr)
        sys.stdout.buffer.write(data)
        return
    proc = subprocess.run(
        [AGE_BIN, "-d", "-i", AGE_KEY_FILE],
        input=data,
        capture_output=True,
    )
    if proc.returncode != 0:
        die(f"age decrypt failed: {proc.stderr.decode(errors='replace')}")
    sys.stdout.buffer.write(proc.stdout)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("clean", "smudge"):
        die("usage: git-age-filter {clean|smudge}")
    (clean if sys.argv[1] == "clean" else smudge)()


if __name__ == "__main__":
    main()
