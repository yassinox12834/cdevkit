"""Merge C/C++ settings into the VS Code user settings.json without losing anything."""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

from . import system


def user_settings_path() -> Path:
    if system.IS_WINDOWS:
        return Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "settings.json"
    if system.IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    return Path.home() / ".config" / "Code" / "User" / "settings.json"


def intellisense_mode() -> str:
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    return f"{system.PLATFORM}-gcc-{arch}"


def _compiler_path() -> Path:
    from .toolchain import find_compiler  # local import: toolchain imports nothing from here
    found = find_compiler("cpp")
    if found:
        return Path(found)
    return system.UCRT_BIN / "g++.exe" if system.IS_WINDOWS else Path("/usr/bin/g++")


def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def toolchain_settings(use_clangd: bool) -> dict:
    compiler = _compiler_path()
    bin_dir = compiler.parent
    settings: dict = {
        "C_Cpp.default.compilerPath": _posix(compiler),
        "C_Cpp.default.intelliSenseMode": intellisense_mode(),
        "C_Cpp.default.cStandard": "c17",
        "C_Cpp.default.cppStandard": "c++20",
        "cmake.generator": "Ninja",
        "cmake.useCMakePresets": "auto",
    }
    # Editor habits (format on save, trailing whitespace) are not set here: they would
    # change every language in every folder. New projects get them in .vscode/settings.json.
    if use_clangd:
        settings.update({
            "C_Cpp.intelliSenseEngine": "disabled",
            "clangd.path": _posix(Path(system.find_tool("clangd") or "clangd")),
            "clangd.arguments": [f"--query-driver={_posix(bin_dir)}/*", "--header-insertion=never"],
        })
    return settings


def merge_settings(existing: dict, new: dict, force: set[str]) -> tuple[dict, list[str], list[str]]:
    """Add `new` keys to `existing`. Keys in `force` are overwritten, others kept.
    Returns (merged, added_or_changed, kept)."""
    merged = dict(existing)
    changed, kept = [], []
    for key, value in new.items():
        if key in merged and key not in force:
            if merged[key] != value:
                kept.append(key)
            continue
        if merged.get(key) != value:
            merged[key] = value
            changed.append(key)
    return merged, changed, kept


KEEP_BACKUPS = 5


def backup_settings(path: Path, text: str) -> Path:
    """Save `text` as settings.json.<date-time>.bak next to `path` and keep the newest few.
    Each backup has its own name, so the original is never overwritten by a later run."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.{stamp}.bak")
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.{stamp}-{n}.bak")
        n += 1
    backup.write_text(text, encoding="utf-8")
    old = sorted(path.parent.glob(path.name + ".*.bak"), key=lambda p: p.stat().st_mtime)
    for extra in old[:-KEEP_BACKUPS]:
        try:
            extra.unlink()
        except OSError:
            pass
    return backup


def apply_toolchain_settings(log: system.Log, use_clangd: bool = False) -> bool:
    path = user_settings_path()
    new = toolchain_settings(use_clangd)
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else "{}"
        existing = json.loads(text) if text.strip() else {}
    except ValueError:
        log(f"warning: {path} contains comments or invalid JSON, so it was not changed.")
        log("Add these lines yourself (Ctrl+Shift+P, 'Preferences: Open User Settings (JSON)'):")
        log(json.dumps(new, indent=2))
        return False
    except OSError as exc:
        log(f"error: cannot read {path}: {exc}")
        return False

    force = {"C_Cpp.default.compilerPath", "clangd.path", "clangd.arguments"}
    merged, changed, kept = merge_settings(existing, new, force)
    if not changed:
        log("VS Code settings already configured.")
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = backup_settings(path, text) if path.exists() else None
        path.write_text(json.dumps(merged, indent=4) + "\n", encoding="utf-8")
    except OSError as exc:
        log(f"error: cannot write {path}: {exc}")
        return False
    log(f"✓ VS Code settings updated ({len(changed)} keys)."
        + (f" Backup saved as {backup.name}." if backup else ""))
    if kept:
        log("Kept your own values for: " + ", ".join(kept))
    return True
