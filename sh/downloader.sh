#!/usr/bin/env bash
# download_backends.sh — fetch build-backend packages from PyPI without pip
set -euo pipefail

DEST="${DEST:-./offline_pkgs}"
WITH_DEPS=0
[[ "${1:-}" == "--with-deps" ]] && WITH_DEPS=1

mkdir -p "$DEST"

# ---- root packages: every backend you might need --------------------------
ROOTS=(
	pip            # useful to ship too
	setuptools     # setuptools.build_meta
	wheel          # legacy editable installs
	setuptools-scm # setuptools VCS versioning
	hatchling      # hatchling.build
	hatch-vcs      # hatch VCS versioning
	flit_core      # flit_core.buildapi
	pdm-backend    # pdm.backend           <-- the one you forgot
	poetry-core    # poetry.core.masonry.api
)

declare -A SEEN

get_json() { curl -fsSL "https://pypi.org/pypi/$1/json"; }

pick_url() {
	python3 -c '
import sys, json
d = json.load(sys.stdin)
for pat in ("-py3-none-any.whl", "-none-any.whl", ".whl", ".tar.gz"):
    for f in d["urls"]:
        if f["filename"].endswith(pat):
            print(f["url"]); sys.exit()
'
}

deps_of() {
	python3 -c '
import sys, json, re
d = json.load(sys.stdin)
for r in (d["info"].get("requires_dist") or []):
    # skip extra-only deps like: foo ; extra == "dev"
    if ";" in r and "extra" in r:
        continue
    name = re.split(r"[\s<>=!~;(\[]", r.strip(), 1)[0]
    if name:
        print(name)
'
}

queue=("${ROOTS[@]}")
while ((${#queue[@]})); do
	pkg="${queue[0]}"
	queue=("${queue[@]:1}")

	# normalize (flit_core vs flit-core, etc.)
	key="${pkg,,}"
	[[ -n "${SEEN[$key]:-}" ]] && continue
	SEEN[$key]=1

	echo "==> $pkg"
	if ! json=$(get_json "$pkg"); then
		echo "  ! PyPI lookup failed"
		continue
	fi

	url=$(printf '%s' "$json" | pick_url)
	if [[ -z "$url" ]]; then
		echo "  ! no distribution found"
		continue
	fi

	fname="${url##*/}"
	echo "  -> $fname"
	curl -fsSL -o "$DEST/$fname" "$url"

	if ((WITH_DEPS)); then
		while IFS= read -r d; do
			[[ -n "$d" ]] && queue+=("$d")
		done < <(printf '%s' "$json" | deps_of)
	fi
done

echo
echo "Done. Files in: $DEST"
ls -1 "$DEST"
