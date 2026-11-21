"""Checks whether components are installed and installs them, on Windows, macOS and Linux.

All methods are blocking: call them from a worker thread, never from the UI thread.
"""

from __future__ import annotations

import os
import shlex
import shutil
import webbrowser

from . import system
from .packs import ALL_COMPONENTS, Component, Pack, install_order
from .vscode_settings import apply_toolchain_settings

# winget exit codes that mean "nothing to do", not failure.
_WINGET_ALREADY = {0x8A15002B, 0x8A150061, -1978335189, -1978335135}

HOMEBREW_INSTALL = '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
VSCODE_DOWNLOAD = "https://code.visualstudio.com/download"

# Microsoft's documented way to add the VS Code repository, then install "code".
VSCODE_SCRIPTS = {
    "apt": (
        "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y wget gpg && "
        "wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor --yes "
        "-o /usr/share/keyrings/microsoft.gpg && "
        "echo 'deb [arch=amd64,arm64,armhf signed-by=/usr/share/keyrings/microsoft.gpg] "
        "https://packages.microsoft.com/repos/code stable main' > /etc/apt/sources.list.d/vscode.list && "
        "apt-get update && apt-get install -y code"
    ),
    "dnf": (
        "rpm --import https://packages.microsoft.com/keys/microsoft.asc && "
        "printf '[code]\\nname=Visual Studio Code\\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\\n"
        "enabled=1\\ngpgcheck=1\\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc\\n' "
        "> /etc/yum.repos.d/vscode.repo && dnf install -y code"
    ),
}

LINUX_INSTALL = {
    "apt": "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y {pkgs}",
    "dnf": "dnf install -y {pkgs}",
    "pacman": "pacman -Sy --needed --noconfirm {pkgs}",
}


class Installer:
    def __init__(self, log: system.Log, platform: str | None = None, manager: str | None = None):
        self.log = log
        self.platform = platform or system.PLATFORM
        self.manager = manager if manager is not None else system.linux_manager()
        self._msys_synced = False
        self._cache: dict[str, set[str]] = {}
        self._waiting_on_user = False

    # ------------------------------------------------------------ helpers
    def source(self, comp: Component):
        return comp.source(self.platform, self.manager)

    def available(self, comp: Component) -> bool:
        return self.source(comp) is not None

    # ------------------------------------------------------------- status
    def invalidate(self) -> None:
        self._cache.clear()
        system.refresh_process_path()

    def _installed_set(self, kind: str) -> set[str]:
        if kind in self._cache:
            return self._cache[kind]
        cmd: list | None = None
        if kind == "msys" and system.MSYS_PACMAN.is_file():
            cmd = [system.MSYS_PACMAN, "-Qq"]
        elif kind in ("brew", "cask") and system.brew_path():
            cmd = [system.brew_path(), "list", "--formula" if kind == "brew" else "--cask", "-1"]
        elif kind == "linux":
            cmd = {
                "apt": ["dpkg-query", "-W", "-f=${db:Status-Abbrev} ${Package}\\n"],
                "dnf": ["rpm", "-qa", "--qf", "%{NAME}\\n"],
                "pacman": ["pacman", "-Qq"],
            }.get(self.manager or "")
        elif kind == "vscode":
            code_cli = system.find_code_cli()
            cmd = [code_cli, "--list-extensions"] if code_cli else None
        names: set[str] = set()
        if cmd:
            rc, out = system.run_capture(cmd, timeout=60)
            if rc == 0:
                for line in out.splitlines():
                    parts = line.split()
                    if not parts:
                        continue
                    if self.manager == "apt" and kind == "linux":
                        if parts[0].startswith("ii") and len(parts) > 1:
                            names.add(parts[-1].split(":")[0])   # drop ":amd64"
                    else:
                        names.add(parts[-1].lower() if kind == "vscode" else parts[-1])
        self._cache[kind] = names
        return names

    def _probe(self, comp: Component) -> bool:
        for probe in comp.probe:
            if "\\" in probe or "/" in probe or "{" in probe:
                if system.expand(probe).exists():
                    return True
            elif system.find_tool(probe) or (probe == "code" and system.find_code_cli()):
                return True
        return False

    def is_installed(self, comp: Component) -> bool:
        src = self.source(comp)
        if src is None:
            return False
        method, ids = src
        if method == "special":
            if ids[0] == "xcode-clt":
                return system.run_capture(["xcode-select", "-p"])[0] == 0
            if ids[0] == "homebrew":
                return system.brew_path() is not None
        if method in ("winget", "script") or (method == "cask" and self._probe(comp)):
            return self._probe(comp)
        if method == "vscode":
            return ids[0].lower() in self._installed_set("vscode")
        if method in ("msys", "brew", "cask", "linux"):
            return all(i in self._installed_set(method) for i in ids)
        return False

    def statuses(self, comps) -> dict[str, bool]:
        self.invalidate()
        return {c.key: self.is_installed(c) for c in comps if self.available(c)}

    # ------------------------------------------------------------ install
    def install(self, comp: Component) -> bool:
        if not self.available(comp):
            self.log(f"{comp.name} is not offered on {system.PLATFORM_NAME}.")
            return False
        for req_key in comp.requires:
            req = ALL_COMPONENTS[req_key]
            if self.available(req) and not self.is_installed(req):
                self.log(f"{comp.name} needs {req.name} first.")
                if not self.install(req):
                    return False
        if self.is_installed(comp):
            self.log(f"✓ {comp.name} is already installed.")
            return True

        self.log(f"Installing {comp.name}...")
        self._waiting_on_user = False
        method, ids = self.source(comp)
        handler = {
            "winget": self._winget, "msys": self._msys, "brew": self._brew, "cask": self._brew,
            "linux": self._linux, "script": self._script, "special": self._special, "vscode": self._vscode,
        }[method]
        ok = handler(method, ids)

        self.invalidate()
        ok = ok and self.is_installed(comp)
        if ok:
            self.log(f"✓ {comp.name} installed.")
        elif self._waiting_on_user:
            self.log(f"Finish {comp.name} in the window that opened, then click Refresh status.")
        else:
            self.log(f"error: {comp.name} did not install. See the log above.")
        return ok

    def install_many(self, comps: list[Component]) -> tuple[int, int]:
        comps = [c for c in comps if self.available(c)]
        if self.platform == "linux":
            self._linux_batch(comps)       # one password prompt for all system packages
        done = failed = 0
        for comp in install_order(comps, self.platform, self.manager):
            if self.install(comp):
                done += 1
            else:
                failed += 1
                if self._waiting_on_user:
                    self.log("Stopped: the remaining items need the step above to finish first.")
                    break
        self.post_configure(comps)
        return done, failed

    def install_pack(self, pack: Pack) -> tuple[int, int]:
        self.log(f"── {pack.title} ──")
        return self.install_many(list(pack.components))

    # ---------------------------------------------------------- configure
    def post_configure(self, comps: list[Component]) -> None:
        """Configuration that runs automatically after installing."""
        methods = {self.source(c)[0] for c in comps if self.available(c)}
        keys = {c.key for c in comps}
        if methods & {"msys", "brew", "special"}:
            state, _ = system.path_status()
            if state == "warn":
                self.log("Configuring: putting the toolchain on PATH.")
                system.configure_path(self.log)
        if keys & {"ext-cpptools", "ext-cmake", "ext-clangd", "gcc", "clang-tools"}:
            if system.find_code_cli():
                apply_toolchain_settings(self.log, use_clangd=self.is_installed(ALL_COMPONENTS["ext-clangd"]))

    # ----------------------------------------------------- Windows methods
    def _winget(self, _method, ids) -> bool:
        winget = system.find_tool("winget")
        if not winget:
            self.log("error: winget was not found. Install 'App Installer' from the Microsoft Store.")
            return False
        self.log("A Windows permission prompt may appear. Accept it to continue.")
        rc = system.run_stream(
            [winget, "install", "--id", ids[0], "--exact", "--silent",
             "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"],
            self.log,
        )
        return rc == 0 or rc in _WINGET_ALREADY

    def _bash(self, script: str) -> int:
        env = os.environ.copy()
        env.update({"MSYSTEM": "UCRT64", "CHERE_INVOKING": "1"})
        return system.run_stream([system.MSYS_BASH, "-lc", script], self.log, env=env)

    def _msys(self, _method, ids) -> bool:
        if not system.MSYS_BASH.is_file():
            self.log(f"error: MSYS2 not found at {system.MSYS_ROOT}.")
            return False
        if not self._msys_synced:
            self.log("Updating MSYS2 package database (first time can take a few minutes)...")
            self._bash("true")  # first start creates the home folder and keyring
            for _ in range(2):  # the first pass may only update the core packages
                self._bash("pacman -Syu --noconfirm --needed")
            self._msys_synced = True
        return self._bash("pacman -S --needed --noconfirm " + " ".join(ids)) == 0

    # ------------------------------------------------------- macOS methods
    def _brew(self, method, ids) -> bool:
        brew = system.brew_path()
        if not brew:
            self.log("error: Homebrew is not installed.")
            return False
        env = os.environ.copy()
        env["HOMEBREW_NO_ENV_HINTS"] = "1"
        cmd = [brew, "install", "--cask", ids[0]] if method == "cask" else [brew, "install", *ids]
        return system.run_stream(cmd, self.log, env=env) == 0

    def _special(self, _method, ids) -> bool:
        if ids[0] == "xcode-clt":
            system.run_stream(["xcode-select", "--install"], self.log)
            self.log("A macOS window asks to install the Command Line Tools: click Install.")
        elif ids[0] == "homebrew":
            self.log("Homebrew asks for your Mac password, so it installs in a Terminal window.")
            system.open_terminal(HOMEBREW_INSTALL)
        self._waiting_on_user = True
        return False

    # ------------------------------------------------------- Linux methods
    def _as_root(self, script: str) -> int:
        """Run a shell script as root: directly if already root, else via a password dialog (pkexec)."""
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return system.run_stream(["sh", "-c", script], self.log)
        if shutil.which("pkexec"):
            self.log("A password dialog will appear: system packages need administrator rights.")
            return system.run_stream(["pkexec", "sh", "-c", script], self.log)
        self.log("No password dialog available: finishing in a terminal with sudo.")
        system.open_terminal("sudo sh -c " + shlex.quote(script))
        self._waiting_on_user = True
        return 1

    def _linux(self, _method, ids) -> bool:
        template = LINUX_INSTALL.get(self.manager or "")
        if not template:
            self.log("error: unsupported Linux distribution (needs apt, dnf or pacman).")
            return False
        return self._as_root(template.format(pkgs=" ".join(shlex.quote(i) for i in ids))) == 0

    def _linux_batch(self, comps: list[Component]) -> None:
        """Install the system packages of all missing components with a single root command."""
        packages: list[str] = []
        for comp in comps:
            src = self.source(comp)
            if src and src[0] == "linux" and not self.is_installed(comp):
                packages += [p for p in src[1] if p not in packages]
        if packages:
            self.log(f"Installing {len(packages)} system packages in one go: {' '.join(packages)}")
            self._linux("linux", tuple(packages))
            self.invalidate()

    def _script(self, _method, ids) -> bool:
        if ids[0] == "vscode":
            script = VSCODE_SCRIPTS.get(self.manager or "")
            if script:
                self.log("Adding Microsoft's VS Code repository, then installing 'code'.")
                return self._as_root(script) == 0
            if shutil.which("snap"):
                return self._as_root("snap install code --classic") == 0
            self.log(f"No automatic VS Code install for this distribution. Opening {VSCODE_DOWNLOAD}")
            webbrowser.open(VSCODE_DOWNLOAD)
            self._waiting_on_user = True
        return False

    # --------------------------------------------------------- all systems
    def _vscode(self, _method, ids) -> bool:
        code_cli = system.find_code_cli()
        if not code_cli:
            self.log("error: VS Code command line ('code') not found. Restart this app after installing VS Code.")
            return False
        return system.run_stream([code_cli, "--install-extension", ids[0]], self.log) == 0
