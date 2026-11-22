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

# Qt draws through a few system libraries. Desktop Linux has them; minimal installs
# (servers, WSL, containers) may not, and then the app cannot open a window.
qt_ready() {
    local err
    if err="$(.venv/bin/python -c 'import PySide6.QtWidgets' 2>&1)"; then
        return 0
    fi
    echo
    echo "The Qt interface is installed but cannot start:"
    echo "  ${err##*$'\n'}"
    if [ "$(uname -s)" = "Linux" ]; then
        echo "Install the system libraries it needs, then run this again:"
        echo "  Debian/Ubuntu: sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3"
        echo "  Fedora:        sudo dnf install mesa-libEGL mesa-libGL libxkbcommon fontconfig dbus-libs"
        echo "  Arch:          sudo pacman -S --needed libglvnd libxkbcommon fontconfig dbus"
    fi
    exit 1
}

# ---- Already set up? -----------------------------------------------------------
# .deps-ok holds a copy of requirements.txt, so an update of the app rebuilds the environment.
if [ -f .venv/.deps-ok ] && cmp -s requirements.txt .venv/.deps-ok &&
   .venv/bin/python -c 'import PySide6' 2>/dev/null; then
    qt_ready
    return 0 2>/dev/null || exit 0
fi
if [ -d .venv ]; then
    echo "Setting up the environment again (the app was updated, or the folder was moved)..."
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
        cp requirements.txt .venv/.deps-ok
        qt_ready
        return 0 2>/dev/null || exit 0
    fi
    echo "That did not work. Trying the private Python instead..."
    rm -rf .venv
fi

# ---- Private Python, kept inside this folder ---------------------------------------
# uv is pinned to one release and checked against its published SHA-256, so a
# changed or tampered download is refused instead of run.
UV_VERSION="0.13.9"
uv_sha256() {
    case "$1" in
        uv-x86_64-apple-darwin)        echo 617a3211261b0fc739562f0071aa34e9739797c510208ede8e2977c30903d041 ;;
        uv-aarch64-apple-darwin)       echo 5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca ;;
        uv-x86_64-unknown-linux-gnu)   echo a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5 ;;
        uv-aarch64-unknown-linux-gnu)  echo 0797542018e541a9288855df555c8077eed06f7a47d206362030480e8ecc9f3d ;;
    esac
}

file_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

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
    url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$target.tar.gz"
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
    if [ "$(file_sha256 "$archive")" != "$(uv_sha256 "$target")" ]; then
        rm -f "$archive"
        fail "The downloaded uv does not match its expected checksum, so it was not used."
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
cp requirements.txt .venv/.deps-ok
qt_ready
