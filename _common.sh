#!/usr/bin/env bash
# Shared by setup.sh and launcher.sh (and the macOS .command files).
#  1. If Python 3.10+ is installed, it is used.
#  2. Otherwise a private Python is downloaded into .runtime/ with uv
#     (https://github.com/astral-sh/uv). Nothing is installed on the system:
#     delete this folder and everything is gone.
# Set CDEVKIT_PORTABLE=1 to always use the private Python.
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
RT="$ROOT/.runtime"

fail() {
    echo
    echo "$1"
    echo "You can also install everything without the app: see docs/install/"
    exit 1
}

# ---- Already set up? -----------------------------------------------------------
if [ -f .venv/.deps-ok ]; then
    if .venv/bin/python -c 'import PySide6.QtWidgets' 2>/dev/null; then
        return 0 2>/dev/null || exit 0
    fi
    echo "The environment no longer works, probably because the folder was moved. Rebuilding it..."
fi
rm -rf .venv

# ---- Look for an installed Python ---------------------------------------------------
PY=""
if [ "${CDEVKIT_PORTABLE:-0}" != "1" ]; then
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 \
                     /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
            PY="$candidate"; break
        fi
    done
fi

if [ -n "$PY" ]; then
    echo "Using your installed Python ($PY). Creating the environment, this takes a minute or two..."
    if "$PY" -m venv .venv && .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
        touch .venv/.deps-ok
        return 0 2>/dev/null || exit 0
    fi
    echo "That did not work. Trying the private Python instead..."
    rm -rf .venv
fi

# ---- Private Python, kept inside this folder ---------------------------------------
uv_target() {
    local arch
    case "$(uname -m)" in
        x86_64|amd64) arch="x86_64" ;;
        arm64|aarch64) arch="aarch64" ;;
        *) return 1 ;;
    esac
    case "$(uname -s)" in
        Darwin) echo "uv-$arch-apple-darwin" ;;
        Linux)  echo "uv-$arch-unknown-linux-gnu" ;;
        *) return 1 ;;
    esac
}

fetch_uv() {
    local target url archive
    target="$(uv_target)" || fail "This computer type ($(uname -s) $(uname -m)) is not supported for the private Python."
    url="https://github.com/astral-sh/uv/releases/latest/download/$target.tar.gz"
    archive="$RT/uv.tar.gz"
    mkdir -p "$RT"
    echo "No suitable Python found. Downloading a private copy into .runtime/ (once, about 60 MB)."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$archive" || return 1
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$url" -O "$archive" || return 1
    else
        fail "Neither curl nor wget is installed, so Python cannot be downloaded."
    fi
    tar -xzf "$archive" -C "$RT" || return 1
    mv -f "$RT/$target/uv" "$RT/uv" && rm -rf "$RT/$target" "$archive"
}

if [ ! -x "$RT/uv" ]; then
    fetch_uv || fail "Could not download Python. Check your internet connection and run this again."
fi

export UV_PYTHON_INSTALL_DIR="$RT/python" UV_CACHE_DIR="$RT/cache" UV_PYTHON_PREFERENCE="only-managed"
echo "Preparing Python 3.12..."
"$RT/uv" venv .venv --python 3.12 --quiet || fail "Could not set up the private Python."
"$RT/uv" pip install --python .venv/bin/python --quiet -r requirements.txt \
    || fail "Could not install the Qt interface. Check your internet connection and run this again."
touch .venv/.deps-ok
