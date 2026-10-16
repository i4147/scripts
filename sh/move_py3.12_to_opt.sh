#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# Termux environment
: "${PREFIX:=/data/data/com.termux/files/usr}"
: "${HOME:=/data/data/com.termux/files/home}"

PYVER="3.12"
SRC="$HOME/.local"
DEST="$PREFIX/opt/python$PYVER"

echo "=== Moving Python $PYVER from $SRC to $DEST ==="

if [ ! -d "$SRC" ]; then
  echo "Error: Source directory $SRC does not exist."
  exit 1
fi

if [ -e "$DEST" ]; then
  echo "Error: Destination $DEST already exists. Remove it first or choose another path."
  exit 1
fi

# Create destination directory structure
mkdir -p "$DEST"/{bin,lib,include,share/man/man1}

shopt -s nullglob

# --- Move Python-specific binaries ---
echo "Moving binaries..."
for f in \
  "$SRC"/bin/python$PYVER \
  "$SRC"/bin/python$PYVER-config \
  "$SRC"/bin/pip$PYVER \
  "$SRC"/bin/pip$PYVER.* \
  "$SRC"/bin/2to3-$PYVER \
  "$SRC"/bin/idle$PYVER \
  "$SRC"/bin/pydoc$PYVER \
  "$SRC"/bin/wheel$PYVER \
  "$SRC"/bin/wheel$PYVER.* \
  "$SRC"/bin/pyvenv-$PYVER \
  "$SRC"/bin/pyvenv; do
  [ -e "$f" ] && mv -v "$f" "$DEST/bin/"
done

# --- Move libraries ---
echo "Moving libraries..."
for f in \
  "$SRC"/lib/python$PYVER \
  "$SRC"/lib/libpython$PYVER.so* \
  "$SRC"/lib/pkgconfig/python-$PYVER.pc; do
  [ -e "$f" ] && mv -v "$f" "$DEST/lib/"
done

# --- Move includes ---
echo "Moving includes..."
for f in "$SRC"/include/python$PYVER; do
  [ -e "$f" ] && mv -v "$f" "$DEST/include/"
done

# --- Move man pages ---
echo "Moving man pages..."
for f in \
  "$SRC"/share/man/man1/python$PYVER.1 \
  "$SRC"/share/man/man1/pip$PYVER.1 \
  "$SRC"/share/man/man1/2to3-$PYVER.1 \
  "$SRC"/share/man/man1/idle$PYVER.1; do
  [ -e "$f" ] && mv -v "$f" "$DEST/share/man/man1/"
done

# --- Create wrapper scripts in $PREFIX/bin ---
echo "Creating wrapper scripts in $PREFIX/bin..."
mkdir -p "$PREFIX/bin"

for f in "$DEST"/bin/*; do
  [ -f "$f" ] || continue
  name=$(basename "$f")
  wrapper="$PREFIX/bin/$name"

  if [ -e "$wrapper" ]; then
    echo "Warning: $wrapper already exists, skipping."
    continue
  fi

  cat > "$wrapper" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
export PYTHONHOME="$DEST"
export LD_LIBRARY_PATH="$DEST/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "$f" "\$@"
EOF
  chmod +x "$wrapper"
  echo "Created $wrapper"
done

# --- Fix shebangs in scripts inside $DEST/bin ---
echo "Fixing shebangs..."
grep -rIl "$SRC" "$DEST/bin" 2>/dev/null | while read -r file; do
  # Point shebangs to the new wrapper in $PREFIX/bin
  sed -i "s|$SRC/bin/|$PREFIX/bin/|g" "$file"
  # Replace any other hardcoded old prefix
  sed -i "s|$SRC|$DEST|g" "$file"
done

# --- Fix sysconfig data and Makefile so pip/setuptools see the new prefix ---
echo "Fixing sysconfig data..."
find "$DEST/lib/python$PYVER" -name "_sysconfigdata*" -type f -exec sed -i "s|$SRC|$DEST|g" {} +
find "$DEST/lib/python$PYVER" -name "Makefile" -type f -exec sed -i "s|$SRC|$DEST|g" {} +

# --- Remove broken symlinks in ~/.local/bin that pointed to moved binaries ---
echo "Cleaning up broken symlinks in $SRC/bin..."
find "$SRC/bin" -xtype l -delete 2>/dev/null || true

# --- Clean up empty directories in ~/.local (but not ~/.local itself) ---
echo "Removing empty directories in $SRC..."
find "$SRC" -mindepth 1 -type d -empty -delete 2>/dev/null || true

echo
echo "=== Done ==="
echo "Python $PYVER is now installed at: $DEST"
echo "Wrappers are available in: $PREFIX/bin"
echo "Try: python$PYVER --version"
echo "     pip$PYVER --version"
echo
echo "If you use bash, you may need to run: hash -r"