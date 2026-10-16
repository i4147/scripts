#!/usr/bin/env bash
set -e

# Define names
ZIP_NAME="termux_configs.zip"
TARGET_PATH="$HOME/$ZIP_NAME"

echo "📦 Gathering configurations..."

# Create a temporary staging directory to map paths neatly
STAGE_DIR=$(mktemp -d)
cd "$STAGE_DIR"

# 1. Copy standard files/directories if they exist
[[ -f "$HOME/.bashrc" ]]       && cp "$HOME/.bashrc" .bashrc
[[ -d "$HOME/.config/bash.d" ]] && mkdir -p .config && cp -r "$HOME/.config/bash.d" .config/
[[ -f "$HOME/.nanorc" ]]       && cp "$HOME/.nanorc" .nanorc
[[ -d "$HOME/.config/nvim" ]]   && mkdir -p .config && cp -r "$HOME/.config/nvim" .config/
[[ -f "$HOME/.gitconfig" ]]    && cp "$HOME/.gitconfig" .gitconfig

# 2. Copy GitHub CLI configurations (including hosts.yml with active session tokens)
if [[ -d "$HOME/.config/gh" ]]; then
    mkdir -p .config/gh
    cp -r "$HOME/.config/gh/"* .config/gh/
fi

# Ensure zip is installed in Termux
if ! command -v zip &> /dev/null; then
    echo "⚙️ Installing zip package..."
    pkg install zip -y
fi

echo "🤐 Compressing workspace into $ZIP_NAME..."
# Zip everything recursively while preserving the dotfile structure
zip -r "$TARGET_PATH" .bashrc .config .nanorc .gitconfig 2>/dev/null || true

# Cleanup staging area
rm -rf "$STAGE_DIR"

echo -e "\n======================================================="
echo "⚠️  SECURITY ALERT"
echo "======================================================="
echo "Your GitHub session tokens are inside this archive!"
echo "DO NOT upload this archive anywhere public (like a public repo)."
echo -e "=======================================================\n"
echo "🎉 Done! Your file is ready at: $TARGET_PATH"
echo "👉 Transfer this file to your computer or upload it directly to Cloud Shell."
