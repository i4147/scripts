#!/bin/bash

# Script to build grpcio Python package for 32-bit ARM Termux
# Run this in Google Cloud Shell (shell.cloud.google.com)

set -e # Exit on any error

# Configuration
PYTHON_VERSION="3.12"   # Adjust if needed
GRPCIO_VERSION="1.60.0" # Change to desired version
OUTPUT_DIR="$HOME/grpcio-build"
TARGET_PLATFORM="linux_armv8l"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== grpcio Builder for 32-bit ARM Termux ===${NC}"
echo -e "${YELLOW}Target: ${TARGET_PLATFORM}${NC}"
echo -e "${YELLOW}Python Version: ${PYTHON_VERSION}${NC}"
echo -e "${YELLOW}grpcio Version: ${GRPCIO_VERSION}${NC}"

# Create working directory
mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR"

# Install required packages
echo -e "${GREEN}[1/6] Installing system dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y \
	build-essential \
	autoconf \
	libtool \
	pkg-config \
	python3 \
	python3-pip \
	python3-dev \
	python3-setuptools \
	python3-wheel \
	git \
	curl \
	cmake \
	ninja-build \
	libssl-dev \
	zlib1g-dev \
	gcc-arm-linux-gnueabihf \
	g++-arm-linux-gnueabihf \
	binutils-arm-linux-gnueabihf

# Install Python packages
echo -e "${GREEN}[2/6] Installing Python build dependencies...${NC}"
pip3 install --user --upgrade pip setuptools wheel cython

# Download grpcio source
echo -e "${GREEN}[3/6] Downloading grpcio ${GRPCIO_VERSION} source...${NC}"
if [ ! -d "grpcio-${GRPCIO_VERSION}" ]; then
	curl -L "https://github.com/grpc/grpc/archive/refs/tags/v${GRPCIO_VERSION}.tar.gz" -o grpc.tar.gz
	tar xzf grpc.tar.gz
	mv "grpc-${GRPCIO_VERSION}" grpcio-src
fi

cd grpcio-src

# Set up cross-compilation environment
echo -e "${GREEN}[4/6] Setting up cross-compilation environment...${NC}"
export CC=arm-linux-gnueabihf-gcc
export CXX=arm-linux-gnueabihf-g++
export AR=arm-linux-gnueabihf-ar
export LD=arm-linux-gnueabihf-ld
export STRIP=arm-linux-gnueabihf-strip
export RANLIB=arm-linux-gnueabihf-ranlib
export CFLAGS="-march=armv8-a -mfpu=neon -mfloat-abi=hard -O2"
export CXXFLAGS="-march=armv8-a -mfpu=neon -mfloat-abi=hard -O2"
export LDFLAGS="-Wl,-rpath-link,/usr/arm-linux-gnueabihf/lib -Wl,-rpath-link,/usr/arm-linux-gnueabihf/lib/arm-linux-gnueabihf"
export PKG_CONFIG_PATH="/usr/arm-linux-gnueabihf/lib/pkgconfig:/usr/lib/arm-linux-gnueabihf/pkgconfig"
export GRPC_PYTHON_BUILD_WITH_CYTHON=1
export GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1
export GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1
export GRPC_PYTHON_BUILD_SYSTEM_CARES=1

# Build grpcio
echo -e "${GREEN}[5/6] Building grpcio...${NC}"
cd "$OUTPUT_DIR/grpcio-src"

# Clean any previous build
python3 setup.py clean --all || true
rm -rf build/ dist/ *.egg-info/

# Build the wheel
python3 setup.py bdist_wheel \
	--dist-dir="$OUTPUT_DIR/dist" \
	--plat-name="$TARGET_PLATFORM"

# Create a custom setup.py modification for better compatibility
echo -e "${GREEN}[6/6] Creating compatible wheel...${NC}"
cd "$OUTPUT_DIR/dist"

# Rename wheel to match Termux platform
for wheel in grpcio-*.whl; do
	if [ -f "$wheel" ]; then
		new_name=$(echo "$wheel" | sed 's/linux_x86_64/linux_armv8l/' | sed 's/cp311/cp312/')
		if [ "$wheel" != "$new_name" ]; then
			mv "$wheel" "$new_name"
			echo -e "${GREEN}Created: $new_name${NC}"
		fi
	fi
done

# Create installation script for Termux
cat >"$OUTPUT_DIR/install_on_termux.sh" <<'EOF'
#!/bin/bash
# Run this script on your Termux device
set -e

echo "Installing grpcio wheel..."
pip install --no-deps --force-reinstall grpcio-*.whl

echo "Installing dependencies..."
pip install protobuf

echo "Verifying installation..."
python3 -c "import grpc; print(f'grpcio version: {grpc.__version__}')"

echo "Installation complete!"
EOF

chmod +x "$OUTPUT_DIR/install_on_termux.sh"

echo -e "${GREEN}=== Build Complete! ===${NC}"
echo -e "${YELLOW}Output files are in: $OUTPUT_DIR/dist/${NC}"
echo -e "${YELLOW}Transfer the .whl file and install_on_termux.sh to your phone${NC}"
echo -e "${YELLOW}Then run on Termux: ./install_on_termux.sh${NC}"

# List built files
ls -la "$OUTPUT_DIR/dist/"
