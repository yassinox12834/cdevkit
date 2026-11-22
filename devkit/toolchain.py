"""Builds the GCC command line used by the launcher. Pure logic, easy to test."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import system

C_STANDARDS = ["c89", "c99", "c11", "c17", "c23"]
CPP_STANDARDS = ["c++98", "c++11", "c++14", "c++17", "c++20", "c++23", "c++26"]
STANDARDS = {"c": C_STANDARDS, "cpp": CPP_STANDARDS}
DEFAULT_STANDARD = {"c": "c17", "cpp": "c++20"}

C_EXTENSIONS = {".c"}
CPP_EXTENSIONS = {".cpp", ".cc", ".cxx", ".c++", ".cp"}
OPTIMISATIONS = ["-O0", "-Og", "-O2", "-O3"]


def detect_language(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in C_EXTENSIONS:
        return "c"
    if ext in CPP_EXTENSIONS:
        return "cpp"
    return None


@dataclass
class BuildOptions:
    language: str = "cpp"          # "c" or "cpp"
    standard: str = "c++20"
    optimisation: str = "-O0"
    warnings: bool = True
    debug: bool = True
    werror: bool = False
    ub_trap: bool = False
    static: bool = False
    gnu: bool = False              # gnu17 instead of c17 (GCC extensions)
    extra_flags: str = ""
    gcc_major: int = 0             # 0 = assume a recent GCC


# Before a standard is final, GCC only accepts its draft name.
# (standard, first GCC major version that knows the final name, draft name)
_DRAFT_NAMES = [
    ("c23", 14, "c2x"),
    ("c++26", 14, "c++2c"),
    ("c++23", 11, "c++2b"),
    ("c++20", 10, "c++2a"),
    ("c17", 8, "c11"),
]


# First GCC major version that accepts each standard under any name.
_MIN_GCC = {"c23": 9, "c++26": 14, "c++23": 11, "c++20": 8}


def supported_standards(language: str, major: int) -> list[str]:
    """Standards the installed GCC can compile. major=0 means unknown: show all."""
    return [s for s in STANDARDS[language] if not major or major >= _MIN_GCC.get(s, 0)]


def std_flag(opts: BuildOptions) -> str:
    std = opts.standard
    if std not in STANDARDS[opts.language]:
        std = DEFAULT_STANDARD[opts.language]
    if opts.gcc_major:
        for final, since, draft in _DRAFT_NAMES:
            if std == final and opts.gcc_major < since:
                std = draft
    if opts.gnu:
        std = "gnu" + std[1:]      # c17 -> gnu17, c++20 -> gnu++20
    return f"-std={std}"


def compiler_name(language: str) -> str:
    return "gcc" if language == "c" else "g++"


def _versioned_gcc(name: str, folders: list[Path]) -> str | None:
    """Highest versioned GCC in `folders`, e.g. g++-15. Homebrew installs GCC this way
    because on macOS plain `gcc` and `g++` are Apple Clang."""
    best: tuple[int, str] | None = None
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob(f"{name}-[0-9]*"):
            suffix = path.name[len(name) + 1:]
            if suffix.isdigit() and (best is None or int(suffix) > best[0]):
                best = (int(suffix), str(path))
    return best[1] if best else None


def find_compiler(language: str) -> str | None:
    name = compiler_name(language)
    if system.IS_MAC:
        found = _versioned_gcc(name, system.extra_bin_dirs())
        if found:
            return found
    return system.find_tool(name)


@dataclass
class CompilerInfo:
    path: str | None
    version: str | None
    is_clang: bool        # True when "gcc" is really Clang (the macOS default)


def compiler_info(language: str = "cpp") -> CompilerInfo:
    exe = find_compiler(language)
    if not exe:
        return CompilerInfo(None, None, False)
    env = system.toolchain_env()
    _, banner = system.run_capture([exe, "--version"], env=env)
    if "clang" in banner.lower():
        return CompilerInfo(exe, system.first_line(banner), True)
    rc, out = system.run_capture([exe, "-dumpfullversion"], env=env)
    return CompilerInfo(exe, out.strip() if rc == 0 else None, False)


def compiler_version(language: str = "cpp") -> str | None:
    info = compiler_info(language)
    return None if info.is_clang else info.version


def gcc_major(version: str | None) -> int:
    try:
        return int((version or "").split(".")[0])
    except ValueError:
        return 0


def collect_sources(main: Path, whole_folder: bool) -> list[Path]:
    """The file itself, or every source file of the same language in its folder."""
    if not whole_folder:
        return [main]
    lang = detect_language(main)
    exts = C_EXTENSIONS if lang == "c" else CPP_EXTENSIONS
    files = sorted(p for p in main.parent.iterdir() if p.is_file() and p.suffix.lower() in exts)
    return files or [main]


def output_path(main: Path) -> Path:
    suffix = ".exe" if system.IS_WINDOWS else ""
    return main.parent / "build" / (main.stem + suffix)


def split_flags(text: str) -> list[str]:
    if not text.strip():
        return []
    if system.IS_WINDOWS:
        # posix=False keeps backslashes in Windows paths; strip quotes afterwards.
        return [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t for t in shlex.split(text, posix=False)]
    return shlex.split(text)


def build_command(compiler: str, sources: list[Path], output: Path, opts: BuildOptions) -> list[str]:
    cmd = [compiler, std_flag(opts), opts.optimisation]
    if opts.debug:
        cmd.append("-g")
    if opts.warnings:
        cmd += ["-Wall", "-Wextra", "-Wpedantic"]
    if opts.werror:
        cmd.append("-Werror")
    if opts.ub_trap:
        # Undefined behaviour stops the program instead of silently continuing.
        # The trap form needs no runtime library, so it works with MinGW.
        cmd += ["-fsanitize=undefined", "-fsanitize-undefined-trap-on-error"]
    if opts.static:
        cmd.append("-static")
    cmd.append("-fdiagnostics-color=never")
    cmd += split_flags(opts.extra_flags)
    cmd += [str(s) for s in sources]
    cmd += ["-o", str(output)]
    if opts.language == "c" and not system.IS_WINDOWS:
        cmd.append("-lm")
    return cmd


# ------------------------------------------------------------------ rebuild check
# After a build, the launcher writes build/<name>.stamp.json with the exact command
# line, the compiler version and every header the sources include. The next run
# rebuilds when any of these changed, not only when a .c/.cpp file is newer.

def stamp_path(output: Path) -> Path:
    return output.parent / (output.name + ".stamp.json")


def dependency_command(compiler: str, sources: list[Path], opts: BuildOptions) -> list[str]:
    """GCC command that lists the user headers the sources include (-MM skips system headers)."""
    return [compiler, std_flag(opts), *split_flags(opts.extra_flags), "-MM", *[str(s) for s in sources]]


def parse_depfile(text: str) -> list[str]:
    """Dependencies from GCC's make-style -MM output.

    Handles line continuations, escaped spaces and Windows drive letters
    ("C:\\x\\a.h" has a colon that is not the rule separator)."""
    deps: list[str] = []
    joined = text.replace("\\\r\n", " ").replace("\\\n", " ")
    for rule in joined.splitlines():
        # The target ends at the first ": " (or ":" at end of line); "C:" is followed by a slash.
        sep = rule.find(": ")
        if sep < 0:
            if rule.rstrip().endswith(":"):
                continue
            sep = rule.find(":")
            if sep < 0:
                continue
        rest = rule[sep + 1:]
        token, i = "", 0
        while i < len(rest):
            ch = rest[i]
            if ch == "\\" and i + 1 < len(rest) and rest[i + 1] == " ":
                token += " "
                i += 2
                continue
            if ch in " \t":
                if token:
                    deps.append(token)
                token = ""
            else:
                token += ch
            i += 1
        if token:
            deps.append(token)
    seen: set[str] = set()
    return [d for d in deps if not (d in seen or seen.add(d))]


def write_stamp(output: Path, cmd: list[str], compiler_version: str | None, deps: list[str]) -> None:
    data = {"command": [str(c) for c in cmd], "compiler": compiler_version or "", "deps": deps}
    try:
        stamp_path(output).write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def needs_build(output: Path, cmd: list[str], compiler_version: str | None, sources: list[Path]) -> tuple[bool, str]:
    """(rebuild?, reason). Rebuilds when the output is missing, the command or the
    compiler changed, or any source or included header is newer than the output."""
    if not output.exists():
        return True, "no executable yet"
    try:
        stamp = json.loads(stamp_path(output).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True, "no record of the last build"
    if stamp.get("command") != [str(c) for c in cmd]:
        return True, "build options changed"
    if stamp.get("compiler", "") != (compiler_version or ""):
        return True, "compiler changed"
    built_at = output.stat().st_mtime
    for dep in [*map(str, sources), *stamp.get("deps", [])]:
        p = Path(dep)
        if not p.exists():
            return True, f"{p.name} is gone"
        if p.stat().st_mtime > built_at:
            return True, f"{p.name} changed"
    return False, "up to date"


def windows_run_script(exe: Path, args: list[str]) -> str:
    """Batch file that runs the program in its own console, shows the exit code and waits.

    Every argument is quoted, so & | < > ^ are literal; % is doubled because
    cmd expands it even inside quotes."""
    def quote(a: str) -> str:
        q = subprocess.list2cmdline([a])
        if not q.startswith('"'):
            q = f'"{q}"'
        return q.replace("%", "%%")
    line = " ".join(quote(a) for a in [str(exe), *args])
    return "\r\n".join(["@echo off", line, "echo.", "echo [exit code %errorlevel%]", "pause", ""])


# Windows crash codes, translated so a crash is not just a big number.
_NTSTATUS = {
    0xC0000005: "access violation: reading or writing memory you do not own (bad pointer, out-of-bounds index)",
    0xC00000FD: "stack overflow: usually infinite recursion",
    0xC0000094: "integer division by zero",
    0xC000001D: "illegal instruction: often an undefined-behaviour trap fired",
    0xC0000409: "stack buffer overrun detected, or abort() was called",
    0xC0000135: "a DLL was not found: add the GCC folder to PATH or enable static linking",
    0xC0000139: "entry point not found: an incompatible DLL is on PATH (mixing MinGW versions?)",
    0x40010004: "the program was closed",
}


def describe_exit(code: int) -> str:
    if code == 0:
        return "exit code 0"
    unsigned = code & 0xFFFFFFFF
    if unsigned in _NTSTATUS:
        return f"exit code 0x{unsigned:08X}, {_NTSTATUS[unsigned]}"
    if code < 0 and not system.IS_WINDOWS:
        import signal
        try:
            return f"killed by signal {signal.Signals(-code).name}"
        except ValueError:
            return f"killed by signal {-code}"
    return f"exit code {code}"
