#!/bin/bash

# Git Configuration Setup Script
# Fill in your details below before running

# ============================================
# EDIT THESE VALUES WITH YOUR INFORMATION
# ============================================

GIT_USERNAME="i4147"
GIT_EMAIL="adnanonagh@gmail.com"
GIT_EDITOR="code --wait" # Change to your preferred editor (vim, nano, code, etc.)
DEFAULT_BRANCH="main"

# ============================================
# DO NOT EDIT BELOW THIS LINE
# ============================================

echo "Setting up Git configuration..."

# Check if values are set
if [[ "$GIT_USERNAME" == "YOUR_USERNAME_HERE" ]] || [[ "$GIT_EMAIL" == "YOUR_EMAIL_HERE" ]]; then
	echo "❌ ERROR: Please edit the script and set your username and email first!"
	echo "   Open the script and replace YOUR_USERNAME_HERE and YOUR_EMAIL_HERE"
	exit 1
fi

# Set global Git configuration
git config --global user.name "$GIT_USERNAME"
git config --global user.email "$GIT_EMAIL"
git config --global core.editor "$GIT_EDITOR"
git config --global init.defaultBranch "$DEFAULT_BRANCH"

# Additional useful configurations
git config --global color.ui auto
git config --global core.autocrlf input # Use 'true' on Windows, 'input' on Mac/Linux
git config --global pull.rebase false
git config --global push.default current

# Optional: Set up credential caching (uncomment if needed)
# git config --global credential.helper cache --timeout=3600  # Cache for 1 hour
# git config --global credential.helper store  # Store permanently (less secure)

echo "✅ Git configuration complete!"
echo ""
echo "Current Git configuration:"
echo "----------------------------------------"
echo "Username: $(git config --global user.name)"
echo "Email: $(git config --global user.email)"
echo "Editor: $(git config --global core.editor)"
echo "Default Branch: $(git config --global init.defaultBranch)"
echo "----------------------------------------"
