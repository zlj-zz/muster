#!/usr/bin/env bash
set -euo pipefail

REPO="zlj-zz/muster"
BRANCH="main"
INSTALL_PREFIX="${INSTALL_PREFIX:-$HOME/.local}"
BIN_DIR="$INSTALL_PREFIX/bin"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { printf "${BLUE}[muster]${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}[muster]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[muster]${NC} %s\n" "$*"; }
err()  { printf "${RED}[muster]${NC} %s\n" "$*" >&2; }

detect_python() {
    if command -v python3.12 >/dev/null 2>&1; then
        echo "python3.12"
    elif command -v python3.11 >/dev/null 2>&1; then
        echo "python3.11"
    elif command -v python3.10 >/dev/null 2>&1; then
        echo "python3.10"
    elif command -v python3 >/dev/null 2>&1; then
        echo "python3"
    else
        echo ""
    fi
}

check_python_version() {
    local py="$1"
    local version
    version=$($py --version 2>&1 | awk '{print $2}')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 10 ]; }; then
        err "Python 3.10+ required, found $version"
        exit 1
    fi
    echo "$version"
}

ensure_pip() {
    local py="$1"
    if ! $py -m pip --version >/dev/null 2>&1; then
        info "pip not found, installing..."
        $py -m ensurepip --upgrade 2>/dev/null || {
            err "Failed to install pip. Please install pip manually."
            exit 1
        }
    fi
}

install_muster() {
    local py="$1"

    info "Installing muster from GitHub ($BRANCH)..."

    # Prefer git+https if git is available
    if command -v git >/dev/null 2>&1; then
        $py -m pip install --quiet --upgrade "git+https://github.com/$REPO.git@$BRANCH"
    else
        # Fallback: download tarball and install
        local tmpdir
        tmpdir=$(mktemp -d)
        trap "rm -rf $tmpdir" EXIT

        info "Downloading source tarball..."
        curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" | tar -xz -C "$tmpdir" --strip-components=1
        $py -m pip install --quiet --upgrade "$tmpdir"
    fi
}

ensure_bin_dir() {
    mkdir -p "$BIN_DIR"
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            warn "$BIN_DIR is not in your PATH."
            warn "Add this to your shell profile:"
            warn "  export PATH=\"$BIN_DIR:\$PATH\""
            ;;
    esac
}

main() {
    echo ""
    info "muster installer"
    info "================"

    local py
    py=$(detect_python)
    if [ -z "$py" ]; then
        err "Python 3 not found. Please install Python 3.10 or newer."
        err "  macOS:  brew install python@3.12"
        err "  Ubuntu: sudo apt install python3.12 python3.12-venv python3.12-pip"
        exit 1
    fi

    local version
    version=$(check_python_version "$py")
    ok "Found Python $version"

    ensure_pip "$py"
    install_muster "$py"

    # Verify installation
    local muster_path
    muster_path=$(command -v muster || true)
    if [ -z "$muster_path" ]; then
        # Check if muster is installed in user site-packages bin
        local user_base
        user_base=$($py -m site --user-base 2>/dev/null || true)
        if [ -n "$user_base" ] && [ -x "$user_base/bin/muster" ]; then
            muster_path="$user_base/bin/muster"
        fi
    fi

    if [ -n "$muster_path" ]; then
        ok "muster installed: $muster_path"
    else
        warn "muster installed but not found in PATH."
    fi

    echo ""
    info "Quick start:"
    info "  muster -f example/muster-compose.yaml"
    echo ""
}

main "$@"
