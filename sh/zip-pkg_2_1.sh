#!/data/data/com.termux/files/usr/bin/bash
VENV_PATH="$HOME/venv"
PYTHON_VERSION="python3.12"
ZIP_DIR="$VENV_PATH/lib/$PYTHON_VERSION/zipped-pkgs"
SITE_PACKAGES="$VENV_PATH/lib/$PYTHON_VERSION/site-packages"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
show_help() {
    echo "Usage: $0 [options] <package-name>"
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -l, --list          List all installed packages"
    echo "  -s, --status        Show zipped packages status"
    echo "  -p, --pyc           Create zip with only .pyc files (remove .py)"
    echo "  -k, --keep-py       Keep .py files in zip (default)"
    echo ""
    echo "Examples:"
    echo "  $0 numpy
    echo "  $0 -p numpy
    echo "  $0 -l
}
check_venv() {
    if [ ! -d "$VENV_PATH" ]; then
        echo -e "${RED}Error: Virtual environment not found at $VENV_PATH${NC}"
        exit 1
    fi
    if [ ! -f "$VENV_PATH/bin/activate" ]; then
        echo -e "${RED}Error: Virtual environment activation script not found${NC}"
        exit 1
    fi
}
run_in_venv() {
    source "$VENV_PATH/bin/activate"
    "$@"
    local exit_code=$?
    deactivate
    return $exit_code
}
list_packages() {
    check_venv
    echo -e "${YELLOW}Installed packages in venv ($VENV_PATH):${NC}"
    run_in_venv pip list --format=columns
}
show_status() {
    check_venv
    echo -e "${YELLOW}Zipped packages in $ZIP_DIR:${NC}"
    if [ -d "$ZIP_DIR" ]; then
        local found=false
        for zipfile in "$ZIP_DIR"/*.zip; do
            if [ -f "$zipfile" ]; then
                found=true
                pkg_name=$(basename "$zipfile" .zip)
                size=$(du -h "$zipfile" | cut -f1)
                if [ -f "$ZIP_DIR/${pkg_name}.pyc-only" ]; then
                    echo -e "  ${GREEN}✓${NC} $pkg_name ($size) ${BLUE}[.pyc only]${NC}"
                else
                    echo -e "  ${GREEN}✓${NC} $pkg_name ($size)"
                fi
            fi
        done
        if [ "$found" = false ]; then
            echo "  No zipped packages found"
        fi
    else
        echo "  No zipped packages found"
    fi
}
create_pyc_only() {
    local pkg_dir="$1"
    local temp_dir="$2"
    cat > "$temp_dir/compile_pyc.py" << 'EOF'
import compileall
import sys
import os
import shutil
def main():
    source_dir = sys.argv[1]
    target_dir = sys.argv[2]
    print(f"Copying {source_dir} to {target_dir}")
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir, ignore=shutil.ignore_patterns('*.so'))
    print(f"Compiling .py files in {target_dir}")
    compileall.compile_dir(
        target_dir,
        force=True,
        legacy=True,
        optimize=2,
        quiet=0,
        rx=re.compile(r'.*\.so$')
    )
    print("Removing original .py files...")
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith('.py'):
                py_path = os.path.join(root, file)
                os.remove(py_path)
    for root, dirs, files in os.walk(target_dir, topdown=False):
        if root.endswith('__pycache__'):
            try:
                os.rmdir(root)
                print(f"Removed {root}")
            except:
                pass
    print(f"Created pyc-only package in {target_dir}")
    return 0
if __name__ == "__main__":
    import re
    sys.exit(main())
EOF
    python "$temp_dir/compile_pyc.py" "$pkg_dir" "$temp_dir/pyc_only"
    echo "$temp_dir/pyc_only"
}
find_package_location() {
    local pkg_name="$1"
    cat > "/data/data/com.termux/files/usr/tmp/find_pkg_$$.py" << EOF
import $pkg_name
import os
try:
    pkg_file = $pkg_name.__file__
    if pkg_file.endswith('__init__.py'):
        print(os.path.dirname(pkg_file))
    elif pkg_file.endswith('.py'):
        print(pkg_file)
    else:
        print(pkg_file)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
EOF
    run_in_venv python "/data/data/com.termux/files/usr/tmp/find_pkg_$$.py"
    local result=$?
    rm -f "/data/data/com.termux/files/usr/tmp/find_pkg_$$.py"
    if [ $result -ne 0 ]; then
        return 1
    fi
}
check_package_exists() {
    local pkg_name="$1"
    run_in_venv pip show "$pkg_name" > /dev/null 2>&1
    return $?
}
zip_package() {
    PKG_NAME="$1"
    PYC_ONLY="$2"
    if [ -z "$PKG_NAME" ]; then
        echo -e "${RED}Error: Package name required${NC}"
        show_help
        exit 1
    fi
    check_venv
    mkdir -p "$ZIP_DIR"
    echo -e "${YELLOW}Checking if package $PKG_NAME exists in venv...${NC}"
    if ! check_package_exists "$PKG_NAME"; then
        echo -e "${RED}Package $PKG_NAME not found in venv!${NC}"
        echo -e "${YELLOW}Installed packages in venv:${NC}"
        list_packages
        exit 1
    fi
    echo -e "${GREEN}Package found. Locating files...${NC}"
    PKG_PATH=$(find_package_location "$PKG_NAME")
    if [ -z "$PKG_PATH" ] || [ "$PKG_PATH" = "ERROR"* ]; then
        echo -e "${RED}Could not find package $PKG_NAME files!${NC}"
        exit 1
    fi
    echo -e "${GREEN}Package location: $PKG_PATH${NC}"
    TMP_DIR="/data/data/com.termux/files/usr/tmp/zip-pkg-$$"
    mkdir -p "$TMP_DIR"
    if [[ -f "$PKG_PATH" ]] && [[ "$PKG_PATH" == *".py" ]]; then
        echo -e "${YELLOW}Package is a single-file module${NC}"
        PKG_DIR=$(dirname "$PKG_PATH")
        PKG_FILE=$(basename "$PKG_PATH")
        cd "$PKG_DIR"
        if [ "$PYC_ONLY" = true ]; then
            echo -e "${YELLOW}Converting single-file module to .pyc only...${NC}"
            python -m py_compile "$PKG_FILE"
            if [ -f "${PKG_FILE}c" ]; then
                zip -9 "$ZIP_DIR/${PKG_NAME}.zip" "${PKG_FILE}c"
                touch "$ZIP_DIR/${PKG_NAME}.pyc-only"
            elif [ -d "__pycache__" ]; then
                cd "__pycache__"
                PYC_FILE=$(ls ${PKG_FILE%.py}*.pyc 2>/dev/null | head -1)
                if [ -n "$PYC_FILE" ]; then
                    zip -9 "$ZIP_DIR/${PKG_NAME}.zip" "$PYC_FILE"
                    cd ..
                    touch "$ZIP_DIR/${PKG_NAME}.pyc-only"
                fi
            fi
            rm -f "$PKG_PATH"
        else
            echo -e "${YELLOW}Zipping single-file module: $PKG_FILE${NC}"
            zip -9 "$ZIP_DIR/${PKG_NAME}.zip" "$PKG_FILE"
            rm -f "$PKG_PATH"
        fi
        cat > "$SITE_PACKAGES/${PKG_NAME}.py" << EOF
import sys, os, zipimport
ZIP_PATH = os.path.join(os.path.dirname(__file__), 'zipped-pkgs', '${PKG_NAME}.zip')
if ZIP_PATH not in sys.path:
    sys.path.insert(0, os.path.dirname(ZIP_PATH))
    importer = zipimport.zipimporter(ZIP_PATH)
    module = importer.load_module('${PKG_NAME}')
    sys.modules['${PKG_NAME}'] = module
EOF
    elif [ -d "$PKG_PATH" ]; then
        echo -e "${YELLOW}Package is a directory module${NC}"
        PKG_NAME_CLEAN=$(basename "$PKG_PATH")
        PKG_PARENT=$(dirname "$PKG_PATH")
        SO_FILES=$(find "$PKG_PATH" -name "*.so" -type f)
        if [ -n "$SO_FILES" ]; then
            echo -e "${YELLOW}Package has C extensions (.so files). Using hybrid approach...${NC}"
            if [ "$PYC_ONLY" = true ]; then
                echo -e "${YELLOW}Creating .pyc-only version for Python files...${NC}"
                SOURCE_DIR=$(create_pyc_only "$PKG_PATH" "$TMP_DIR")
                if [ -d "$SOURCE_DIR" ]; then
                    touch "$ZIP_DIR/${PKG_NAME}.pyc-only"
                    cd "$TMP_DIR"
                    zip -9 -r "$ZIP_DIR/${PKG_NAME}.zip" "$PKG_NAME_CLEAN"
                else
                    echo -e "${RED}Failed to create pyc-only version${NC}"
                    exit 1
                fi
            else
                cd "$PKG_PARENT"
                zip -9 -r "$ZIP_DIR/${PKG_NAME}.zip" "$PKG_NAME_CLEAN" -x "*.so"
            fi
            if [ -n "$SO_FILES" ]; then
                mkdir -p "$ZIP_DIR/${PKG_NAME}_libs"
                cp -r "$PKG_PATH" "$ZIP_DIR/${PKG_NAME}_libs/"
                find "$ZIP_DIR/${PKG_NAME}_libs" -name "*.py" -type f -delete
                find "$ZIP_DIR/${PKG_NAME}_libs" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
            fi
            rm -rf "$PKG_PATH"
            cat > "$SITE_PACKAGES/${PKG_NAME}.py" << EOF
import sys, os, zipimport
ZIP_PATH = os.path.join(os.path.dirname(__file__), 'zipped-pkgs', '${PKG_NAME}.zip')
LIBS_PATH = os.path.join(os.path.dirname(__file__), 'zipped-pkgs', '${PKG_NAME}_libs')
if LIBS_PATH not in sys.path:
    sys.path.insert(0, LIBS_PATH)
    sys.path.insert(0, os.path.join(LIBS_PATH, '${PKG_NAME_CLEAN}'))
if ZIP_PATH not in sys.path:
    sys.path.insert(0, os.path.dirname(ZIP_PATH))
try:
    module = __import__('${PKG_NAME}')
except ImportError as e:
    importer = zipimport.zipimporter(ZIP_PATH)
    module = importer.load_module('${PKG_NAME}')
sys.modules['${PKG_NAME}'] = module
EOF
        else:
            if [ "$PYC_ONLY" = true ]; then
                echo -e "${GREEN}Creating .pyc-only zip package...${NC}"
                SOURCE_DIR=$(create_pyc_only "$PKG_PATH" "$TMP_DIR")
                if [ -d "$SOURCE_DIR" ]; then
                    touch "$ZIP_DIR/${PKG_NAME}.pyc-only"
                    cd "$TMP_DIR"
                    zip -9 -r "$ZIP_DIR/${PKG_NAME}.zip" "$PKG_NAME_CLEAN"
                else
                    echo -e "${RED}Failed to create pyc-only version${NC}"
                    exit 1
                fi
            else
                echo -e "${GREEN}Creating full zip package (keeping .py files)...${NC}"
                cd "$PKG_PARENT"
                zip -9 -r "$ZIP_DIR/${PKG_NAME}.zip" "$PKG_NAME_CLEAN"
            fi
            rm -rf "$PKG_PATH"
            cat > "$SITE_PACKAGES/${PKG_NAME}.py" << EOF
import sys, os
ZIP_PATH = os.path.join(os.path.dirname(__file__), 'zipped-pkgs', '${PKG_NAME}.zip')
if ZIP_PATH not in sys.path:
    sys.path.insert(0, os.path.dirname(ZIP_PATH))
module = __import__('${PKG_NAME}')
sys.modules['${PKG_NAME}'] = module
EOF
        fi
    else:
        echo -e "${RED}Unknown package type: $PKG_PATH${NC}"
        exit 1
    fi
    rm -rf "$TMP_DIR"
    echo -e "${GREEN}✓ Package $PKG_NAME converted to zip format${NC}"
    echo -e "${GREEN}  Location: $ZIP_DIR/${PKG_NAME}.zip${NC}"
    local zip_size=$(du -h "$ZIP_DIR/${PKG_NAME}.zip" | cut -f1)
    echo -e "${GREEN}  Zip size: $zip_size${NC}"
    if [ "$PYC_ONLY" = true ]; then
        echo -e "${BLUE}  Mode: .pyc only (original .py files removed)${NC}"
    else
        echo -e "${YELLOW}  Mode: Keeping .py files${NC}"
    fi
    echo -e "${YELLOW}Verifying zip file...${NC}"
    unzip -t "$ZIP_DIR/${PKG_NAME}.zip" > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ Zip file is valid${NC}"
    else
        echo -e "${RED}  ✗ Zip file may be corrupted${NC}"
    fi
}
PYC_ONLY=false
PACKAGE_NAME=""
while [[ $
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -l|--list)
            list_packages
            exit 0
            ;;
        -s|--status)
            show_status
            exit 0
            ;;
        -p|--pyc)
            PYC_ONLY=true
            shift
            ;;
        -k|--keep-py)
            PYC_ONLY=false
            shift
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
        *)
            PACKAGE_NAME="$1"
            shift
            ;;
    esac
done
if [ -n "$PACKAGE_NAME" ]; then
    zip_package "$PACKAGE_NAME" "$PYC_ONLY"
else
    show_help
fi
