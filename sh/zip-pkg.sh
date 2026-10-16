#!/bin/bash
PYTHON_VERSION="python3.12"
SITE_PACKAGES="/data/data/com.termux/files/usr/lib/$PYTHON_VERSION/site-packages"
ZIP_DIR="/data/data/com.termux/files/usr/lib/$PYTHON_VERSION/site-packages"
CYAN='\033[0;96m'
GREEN='\033[0;92m'
YELLOW='\033[1;93m'
NC='\033[0m'
USE_PYC=false
PKG_NAME=""
while [[ "$
	case $1 in
	-p | --pyc) USE_PYC=true ;;
	*) PKG_NAME="$1" ;;
	esac
	shift
done
if [ -z "$PKG_NAME" ]; then
	echo -e "${CYAN}Usage: $0 [-p] <package-name>${NC}"
	echo "Options: -p, --pyc    Store as compiled bytecode (.pyc) instead of source (.py)"
	exit 1
fi
mkdir -p "$ZIP_DIR"
PKG_PATH=$(python -c "import $PKG_NAME; print($PKG_NAME.__file__)" 2>/dev/null | sed 's/__init__.py//' | sed 's/\.py$//')
if [ -z "$PKG_PATH" ]; then
	echo -e "${CYAN}Package $PKG_NAME not found!${NC}"
	exit 1
fi
TMP_DIR="/data/data/com.termux/files/usr/tmp/zip-pkg-$$"
mkdir -p "$TMP_DIR"
echo -e "${YELLOW}Step 1: Preparing $PKG_NAME...${NC}"
if [[ "$PKG_PATH" == *".py" ]]; then777
	echo "--- Single File Module Handling ---"
	exit $1
fi
else
	PKG_NAME_CLEAN=$(basename "$PKG_PATH")
	cp -r "$PKG_PATH" "$TMP_DIR/"
	if [ "$USE_PYC" = true ]; then
		echo -e "${YELLOW}Compiling package to bytecode...${NC}"
		python -m compileall -b -q "$TMP_DIR/$PKG_NAME_CLEAN"
		find "$TMP_DIR/$PKG_NAME_CLEAN" -name "*.py" -delete
		find "$TMP_DIR/$PKG_NAME_CLEAN" -name "__pycache__" -type d -exec rm -rf {} +
	fi
	cd "$TMP_DIR"
	SO_FILES=$(find "$PKG_NAME_CLEAN" -name "*.so" -type f)
	if [ -n "$SO_FILES" ]; then
    echo "we process just pure pkgs."
    exit $1
	zip -9 -r "$ZIP_DIR/${PKG_NAME}.zip" "$PKG_NAME_CLEAN"
	rm -rf "$PKG_PATH"
fi
cat >"$SITE_PACKAGES/${PKG_NAME}.py" <<EOF
import sys, os
ZIP_PATH = os.path.join('$ZIP_DIR', '${PKG_NAME}.zip')
LIBS_PATH = os.path.join('$ZIP_DIR', '${PKG_NAME}_libs')
if os.path.exists(LIBS_PATH) and LIBS_PATH not in sys.path: sys.path.insert(0, LIBS_PATH)
if ZIP_PATH not in sys.path: sys.path.insert(0, ZIP_PATH)
module = __import__('${PKG_NAME}')
sys.modules['${PKG_NAME}'] = module
EOF
rm -rf "$TMP_DIR"
echo -e "${GREEN}✓ $PKG_NAME zipped successfully (Mode: $([ "$USE_PYC" = true ] && echo ".pyc" || echo ".py"))${NC}"
