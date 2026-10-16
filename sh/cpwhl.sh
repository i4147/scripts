#!/bin/bash

set -e

VERSION="1.28.2"
ARCH="arm" # This targets armv7l/armv8l 32-bit Termux installations
SHA256="23a64814bb9dce3088256c6bed981b03a163aa232a6f698180432b9a5990a891"
PACKAGE_NAME="python-pymupdf"

echo "----------------------------------------------------------------"
echo "Starting PyMuPDF $VERSION Cross-Compilation for Termux $ARCH"
echo "----------------------------------------------------------------"

if [ ! -d "termux-packages" ]; then
    echo "[*] Cloning termux-packages repository..."
#    git clone --depth 1 https://github.com/termux/termux-packages.git
else
    echo "[*] termux-packages directory already exists. Using existing."
fi

cd termux-packages

# 2. Update the build script to the target version
echo "[*] Configuring build recipe for PyMuPDF $VERSION..."
BUILD_SH="packages/$PACKAGE_NAME/build.sh"

if [ ! -f "$BUILD_SH" ]; then
    echo "[!] Error: Could not find build script at $BUILD_SH"
    exit 1
fi

# Apply the version and checksum updates
sed -i "s/^TERMUX_PKG_VERSION=.*/TERMUX_PKG_VERSION=\"$VERSION\"/" "$BUILD_SH"
sed -i "s/^TERMUX_PKG_SHA256=.*/TERMUX_PKG_SHA256=$SHA256/" "$BUILD_SH"
sed -i "s/^TERMUX_PKG_REVISION=.*/TERMUX_PKG_REVISION=0/" "$BUILD_SH"

# Inject a command to copy the generated wheel out of the Docker container
# Termux-packages mounts the host directory to /home/builder/termux-packages
if ! grep -q "cp dist/\*.whl" "$BUILD_SH"; then
    echo "[*] Patching build script to extract the wheel..."
    # We append the copy command after the 'pip install' line in the make_install step
    sed -i '/pip install/a \	cp dist/*.whl /home/builder/termux-packages/' "$BUILD_SH"
fi

# 3. Execute the build in Docker
# The Termux build system uses a pre-configured Docker image (ghcr.io/termux/package-builder)
# which contains the Android NDK and all cross-compilation toolchains.
echo "[*] Launching Docker container for compilation..."
echo "[*] This may take 5-10 minutes as it builds C extensions."

# Run the build-package command inside the container
./scripts/run-docker.sh ./build-package.sh -a $ARCH $PACKAGE_NAME

# 4. Retrieve the resulting wheel
cd ..
WHEEL_FILE=$(ls termux-packages/*.whl 2>/dev/null | head -n 1)

if [ -n "$WHEEL_FILE" ]; then
    WHEEL_NAME=$(basename "$WHEEL_FILE")
    mv "$WHEEL_FILE" .

    echo ""
    echo "================================================================"
    echo "SUCCESS! $WHEEL_NAME has been created."
    echo "================================================================"
    echo "INSTALLATION STEPS FOR YOUR PHONE:"
    echo "1. Transfer '$WHEEL_NAME' to your Samsung A5 2016."
    echo "2. Open Termux and install the system dependencies:"
    echo "   pkg update && pkg install mupdf libjpeg-turbo freetype"
    echo "3. Install the wheel using pip:"
    echo "   pip install ./$WHEEL_NAME"
    echo "================================================================"
else
    echo ""
    echo "[!] ERROR: The build finished but no .whl file was found in the output directory."
    echo "[!] Please check the build logs above for compilation errors."
fi
