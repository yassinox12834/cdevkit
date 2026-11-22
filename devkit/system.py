"""Operating-system helpers: running commands, PATH handling, finding tools.

Everything Windows-specific lives here so the rest of the code stays readable.
"""

from __future__ import annotations

import io
import json
import os
import signal
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Sequence

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MAC
PLATFORM = "windows" if IS_WINDOWS else "macos" if IS_MAC else "linux"
PLATFORM_NAME = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}[PLATFORM]

# Homebrew lives in /opt/homebrew on Apple Silicon and /usr/local on Intel Macs.
BREW_PREFIXES = (Path("/opt/homebrew"), Path("/usr/local"))

# MSYS2 location. Override with the CDEVKIT_MSYS_ROOT environment variable
# if you installed MSYS2 somewhere other than C:\msys64.
MSYS_ROOT = Path(os.environ.get("CDEVKIT_MSYS_ROOT", r"C:\msys64"))
MSYS_BASH = MSYS_ROOT / "usr" / "bin" / "bash.exe"
MSYS_PACMAN = MSYS_ROOT / "usr" / "bin" / "pacman.exe"
UCRT_BIN = MSYS_ROOT / "ucrt64" / "bin"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010

APP_DIR = Path.home() / ".cdevkit"

Log = Callable[[str], None]


# --------------------------------------------------------------------------
# Running commands
# --------------------------------------------------------------------------

def format_cmd(cmd: Sequence[str]) -> str:
    parts = [str(c) for c in cmd]
    return subprocess.list2cmdline(parts) if IS_WINDOWS else shlex.join(parts)


def _hidden_window() -> dict:
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def _own_group() -> dict:
    """Start the child in its own process group, so it can be stopped with everything it started."""
    return {} if IS_WINDOWS else {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    """Stop a process and every process it started. Never raises."""
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                           timeout=15, **_hidden_window())
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


# Cancel button support: every command started by run_stream is registered here,
# so the UI can stop whatever is running, from any thread.
_running: set[subprocess.Popen] = set()
_running_lock = threading.Lock()
_cancel = threading.Event()


def cancel_running() -> None:
    """Stop every running command and make new ones refuse to start until reset_cancel()."""
    _cancel.set()
    with _running_lock:
        procs = list(_running)
    for proc in procs:
        kill_tree(proc)


def reset_cancel() -> None:
    _cancel.clear()


def cancelled() -> bool:
    return _cancel.is_set()


EXIT_CANCELLED = 130
EXIT_TIMEOUT = 124


_SPINNER = {"", "-", "\\", "|", "/"}


def run_stream(
    cmd: Sequence[str],
    log: Log,
    *,
    env: dict | None = None,
    cwd: str | Path | None = None,
    echo: bool = True,
    timeout: float | None = None,
) -> int:
    """Run a command and send each output line to `log`. Returns the exit code.

    `timeout` is in seconds; when it runs out the command and its children are
    stopped and EXIT_TIMEOUT is returned. cancel_running() stops it too
    (EXIT_CANCELLED)."""
    if _cancel.is_set():
        return EXIT_CANCELLED
    if echo:
        log("$ " + format_cmd(cmd))
    try:
        proc = subprocess.Popen(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=cwd,
            **_hidden_window(),
            **_own_group(),
        )
    except FileNotFoundError:
        log(f"error: command not found: {cmd[0]}")
        return 127
    except OSError as exc:
        log(f"error: could not start {cmd[0]}: {exc}")
        return 126

    assert proc.stdout is not None
    with _running_lock:
        _running.add(proc)
    timed_out = threading.Event()
    finished = threading.Event()

    def watchdog() -> None:
        if not finished.wait(timeout):
            timed_out.set()
            kill_tree(proc)
    if timeout:
        threading.Thread(target=watchdog, daemon=True).start()
    # newline="\n": split lines on \n only, so the \r of a progress bar stays inside
    # the line and _pump can keep just its last frame.
    stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace", newline="\n")
    try:
        _pump(stream, log)
        rc = proc.wait()
    finally:
        stream.close()
        finished.set()
        with _running_lock:
            _running.discard(proc)
    if timed_out.is_set():
        log(f"error: stopped after {timeout:.0f} s without finishing: {Path(str(cmd[0])).name}")
        return EXIT_TIMEOUT
    if _cancel.is_set():
        log("Cancelled.")
        return EXIT_CANCELLED
    return rc


def _pump(stream: io.TextIOWrapper, log: Log) -> None:
    for raw in stream:
        # winget redraws progress bars with carriage returns: keep the last frame.
        line = raw.rstrip("\r\n").split("\r")[-1].rstrip()
        if line.strip() in _SPINNER:
            continue
        if line.startswith("(Reading database ...") and not line.endswith(".)"):
            continue  # apt progress counter
        log(line)


def run_capture(cmd: Sequence[str], *, timeout: float = 20, env: dict | None = None,
                cwd: str | Path | None = None) -> tuple[int, str]:
    """Run a command quietly and return (exit code, combined output)."""
    try:
        res = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            **_hidden_window(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


# --------------------------------------------------------------------------
# PATH handling (Windows registry)
# --------------------------------------------------------------------------

def _norm(p: str) -> str:
    return os.path.normcase(os.path.expandvars(p.strip()).rstrip("\\/"))


def _read_registry_path(user: bool) -> tuple[str, int]:
    import winreg

    if user:
        root, sub = winreg.HKEY_CURRENT_USER, "Environment"
    else:
        root = winreg.HKEY_LOCAL_MACHINE
        sub = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    try:
        with winreg.OpenKey(root, sub) as key:
            value, kind = winreg.QueryValueEx(key, "Path")
            return value, kind
    except OSError:
        return "", winreg.REG_EXPAND_SZ


def refresh_process_path() -> None:
    """Reload PATH from the registry, so tools installed a moment ago are found
    without restarting the app."""
    if not IS_WINDOWS:
        return
    machine, _ = _read_registry_path(user=False)
    user, _ = _read_registry_path(user=True)
    seen: set[str] = set()
    merged: list[str] = []
    for entry in os.environ.get("PATH", "").split(";") + machine.split(";") + user.split(";"):
        entry = os.path.expandvars(entry.strip())
        key = _norm(entry)
        if entry and key not in seen:
            seen.add(key)
            merged.append(entry)
    os.environ["PATH"] = ";".join(merged)


def prepend_path_entry(value: str, directory: str, sep: str = ";") -> str:
    """`value` (a PATH string) with `directory` first, and any other copy of it removed.

    First matters: Windows takes the first gcc.exe it finds, so an old MinGW
    earlier on PATH would win and cause crash 0xC0000139."""
    target = _norm(directory)
    rest = [p for p in value.split(sep) if p.strip() and _norm(p) != target]
    return sep.join([directory, *rest])


def path_shadow(name: str, expected_dir: Path, path_value: str | None = None) -> Path | None:
    """The folder that provides `name` first on PATH, when it is not `expected_dir`.

    None means the toolchain wins (or `name` is on PATH nowhere)."""
    exe = name + ".exe" if IS_WINDOWS and not name.lower().endswith(".exe") else name
    for entry in (path_value if path_value is not None else os.environ.get("PATH", "")).split(os.pathsep):
        if not entry.strip():
            continue
        folder = Path(os.path.expandvars(entry.strip()))
        if (folder / exe).is_file():
            return None if _norm(str(folder)) == _norm(str(expected_dir)) else folder
    return None


def path_conflicts() -> list[str]:
    """Warnings about other compilers that come before the toolchain on PATH (Windows)."""
    if not IS_WINDOWS or not UCRT_BIN.is_dir():
        return []
    refresh_process_path()
    machine, _ = _read_registry_path(user=False)
    user, _ = _read_registry_path(user=True)
    # New terminals see the system PATH first, then the user PATH.
    full = ";".join(p for p in (machine, user) if p)
    warnings = []
    for tool in ("gcc", "g++", "gdb"):
        other = path_shadow(tool, UCRT_BIN, full)
        if other:
            warnings.append(f"{tool} from {other} comes before {UCRT_BIN} on PATH")
    return warnings


def user_path_contains(directory: Path) -> bool:
    if not IS_WINDOWS:
        return str(directory) in os.environ.get("PATH", "").split(os.pathsep)
    target = _norm(str(directory))
    for scope in (True, False):
        value, _ = _read_registry_path(user=scope)
        if any(_norm(p) == target for p in value.split(";") if p.strip()):
            return True
    return False


def add_to_user_path(directory: Path, log: Log) -> bool:
    """Put `directory` first on the user PATH. Returns True if something changed."""
    if not IS_WINDOWS:
        log("PATH editing is only done on Windows.")
        return False
    import ctypes
    import winreg

    value, kind = _read_registry_path(user=True)
    new_value = prepend_path_entry(value, str(directory))
    if new_value == value:
        log(f"{directory} is already first on your user PATH.")
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, kind or winreg.REG_EXPAND_SZ, new_value)
    # Tell running programs (Explorer, new terminals) that the environment changed.
    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
    refresh_process_path()
    log(f"Put {directory} first on your user PATH. Open a new terminal to see it.")
    for warning in path_conflicts():
        log("warning: " + warning + ". Remove the other one from the system PATH, or link statically.")
    return True


# --------------------------------------------------------------------------
# Finding tools
# --------------------------------------------------------------------------

def extra_bin_dirs() -> list[Path]:
    """Folders searched before PATH. Apps started from Finder or the Start menu
    often have a short PATH, so the toolchain folders are added explicitly."""
    if IS_WINDOWS:
        return [UCRT_BIN]
    if IS_MAC:
        dirs: list[Path] = []
        for prefix in BREW_PREFIXES:
            # llvm is "keg-only": Homebrew does not link clang-tidy/clangd into bin.
            dirs += [prefix / "bin", prefix / "opt" / "llvm" / "bin"]
        return dirs
    return []


def toolchain_env() -> dict:
    """Environment with the toolchain folders first on PATH."""
    env = os.environ.copy()
    extra = [str(d) for d in extra_bin_dirs() if d.is_dir()]
    if extra:
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def find_tool(name: str) -> str | None:
    """Find an executable in the toolchain folders, then on PATH."""
    exe = name + ".exe" if IS_WINDOWS and not name.endswith(".exe") else name
    for folder in extra_bin_dirs():
        candidate = folder / exe
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def brew_path() -> str | None:
    for prefix in BREW_PREFIXES:
        candidate = prefix / "bin" / "brew"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("brew")


def linux_manager() -> str | None:
    """Which package manager this Linux distribution uses."""
    if not IS_LINUX:
        return None
    for name, exe in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman")):
        if shutil.which(exe):
            return name
    return None


def expand(path: str) -> Path:
    return Path(os.path.expandvars(path.replace("{msys}", str(MSYS_ROOT))))


def find_code_cli() -> str | None:
    """Path to the VS Code command-line launcher (code.cmd on Windows)."""
    found = shutil.which("code")
    if found:
        return found
    for raw in (
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd",
        r"%ProgramFiles%\Microsoft VS Code\bin\code.cmd",
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
        "/snap/bin/code",
    ):
        p = expand(raw)
        if p.is_file():
            return str(p)
    return None


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


# --------------------------------------------------------------------------
# Opening things
# --------------------------------------------------------------------------

def _applescript_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_terminal(command: str, cwd: str | Path | None = None) -> None:
    """Open a new terminal window running `command`, which stays open afterwards."""
    if IS_WINDOWS:
        subprocess.Popen(["cmd.exe", "/k", command], cwd=cwd, creationflags=CREATE_NEW_CONSOLE, env=toolchain_env())
        return
    script = f"cd {shlex.quote(str(cwd))} && {command}" if cwd else command
    if IS_MAC:
        subprocess.Popen(["osascript",
                          "-e", f'tell application "Terminal" to do script {_applescript_str(script)}',
                          "-e", 'tell application "Terminal" to activate'])
        return
    keep_open = f"{script}; exec bash"
    for term, args in (("gnome-terminal", ["--", "bash", "-c", keep_open]),
                       ("konsole", ["-e", "bash", "-c", keep_open]),
                       ("xfce4-terminal", ["-x", "bash", "-c", keep_open]),
                       ("x-terminal-emulator", ["-e", "bash", "-c", keep_open]),
                       ("xterm", ["-e", "bash", "-c", keep_open])):
        if shutil.which(term):
            subprocess.Popen([term, *args], env=toolchain_env())
            return
    raise RuntimeError("No terminal emulator found.")


def open_in_vscode(path: str | Path, line: int | None = None) -> bool:
    code = find_code_cli()
    if not code:
        return False
    target = f"{path}:{line}" if line else str(path)
    subprocess.Popen([code, "-g", target], **_hidden_window())
    return True


def open_folder(path: str | Path) -> None:
    if IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif IS_MAC:
        subprocess.Popen(["open", str(path)])
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)])


# --------------------------------------------------------------------------
# "Is the toolchain on PATH?" for each platform
# --------------------------------------------------------------------------

_SHELL_FILES = (".zprofile", ".zshrc", ".bash_profile", ".profile")


def _brew_shellenv_configured(brew: str) -> bool:
    prefix = str(Path(brew).parent)
    if prefix == "/usr/local/bin":
        return True                      # already on the default macOS PATH
    for name in _SHELL_FILES:
        try:
            if "brew shellenv" in (Path.home() / name).read_text(encoding="utf-8"):
                return True
        except OSError:
            continue
    return False


def path_status() -> tuple[str, str]:
    """(dot state, explanation) for the Configure page."""
    if IS_WINDOWS:
        if not UCRT_BIN.is_dir():
            return "missing", "GCC not installed yet"
        if user_path_contains(UCRT_BIN):
            conflicts = path_conflicts()
            if conflicts:
                return "warn", conflicts[0]
            return "ok", f"{UCRT_BIN} is on PATH"
        return "warn", "GCC is installed but not on PATH"
    if IS_MAC:
        brew = brew_path()
        if not brew:
            return "missing", "Homebrew not installed yet"
        if _brew_shellenv_configured(brew):
            return "ok", "Homebrew tools are on PATH"
        return "warn", "Homebrew is installed but not on PATH"
    return "ok", "Linux packages go straight onto PATH, nothing to do"


def configure_path(log: Log) -> bool:
    if IS_WINDOWS:
        if not UCRT_BIN.is_dir():
            log(f"error: {UCRT_BIN} does not exist. Install the Classic pack first.")
            return False
        return add_to_user_path(UCRT_BIN, log)
    if IS_MAC:
        brew = brew_path()
        if not brew:
            log("error: Homebrew is not installed. Install the Classic pack first.")
            return False
        if _brew_shellenv_configured(brew):
            log("Homebrew is already on PATH.")
            return False
        profile = Path.home() / ".zprofile"
        with profile.open("a", encoding="utf-8") as fh:
            fh.write(f'\n# Added by C/C++ DevKit\neval "$({brew} shellenv)"\n')
        log(f"✓ Added Homebrew to {profile}. Open a new Terminal window to see it.")
        return True
    log("Nothing to do on Linux: packages are installed into /usr/bin.")
    return False


# --------------------------------------------------------------------------
# Small JSON settings store
# --------------------------------------------------------------------------

class Settings:
    """A dict saved to ~/.cdevkit/<name>.json. Safe to use from one thread."""

    def __init__(self, name: str):
        self.path = APP_DIR / f"{name}.json"
        self._lock = threading.Lock()
        try:
            self.data: dict = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    def save(self) -> None:
        with self._lock:
            try:
                APP_DIR.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            except OSError:
                pass
