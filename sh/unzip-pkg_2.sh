#!/bin/bash
PKG_NAME="$1"
PYTHON_VERSION="python3.12"
SITE_PACKAGES="/data/data/com.termux/files/usr/lib/$PYTHON_VERSION/site-packages"
ZIP_DIR="/data/data/com.termux/files/usr/lib/$PYTHON_VERSION/zipped-pkgs"
if [ -z "$PKG_NAME" ]; then
	echo "Usage: $0 <package-name>"
	exit 1
fi
echo "Restoring $PKG_NAME from zip..."
rm -f "$SITE_PACKAGES/${PKG_NAME}.py"
unzip -o "$ZIP_DIR/${PKG_NAME}.zip" -d "$SITE_PACKAGES/"
if [ -d "$ZIP_DIR/${PKG_NAME}_libs" ]; then
	cp -r "$ZIP_DIR/${PKG_NAME}_libs/"* "$SITE_PACKAGES/"
	rm -rf "$ZIP_DIR/${PKG_NAME}_libs"
fi
rm "$ZIP_DIR/${PKG_NAME}.zip"
echo "✓ $PKG_NAME restored to $SITE_PACKAGES (Bytecode version)"
