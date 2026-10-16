#!/bin/bash

TEXT_FILE="${1:-missing.txt}"

if [[ ! -f "$TEXT_FILE" ]]; then
    echo "Error: $TEXT_FILE not found"
    exit 1
fi

mapfile -t packages < "$TEXT_FILE"

# Remove empty lines
packages=( "${packages[@]//[[:space:]]/}" )
packages=( "${packages[@]##}" )
packages=( "${packages[@]%%" )

if [[ ${#packages[@]} -eq 0 ]]; then
    echo "No packages to reinstall"
    exit 0
fi

echo "Found ${#packages[@]} packages with missing files"
echo "Packages to reinstall:"
printf '  %s\n' "${packages[@]}"

for pkg in "${packages[@]}"; do
    echo "Installing: $pkg"
    apt install --reinstall -y "$pkg" || echo "  ✗ Failed to reinstall $pkg"
done

echo "✓ Reinstall complete"
