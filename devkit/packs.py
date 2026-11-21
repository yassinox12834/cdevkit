"""The packs offered by the setup app, for Windows, macOS and Linux.

Each Component says how to get it on each platform:
  Windows  winget id (a program) or MSYS2 packages (the GCC toolchain)
  macOS    Homebrew formulae or a cask (a program), or a special step
  Linux    package names for apt (Debian, Ubuntu, Mint), dnf (Fedora) and pacman (Arch)
  all      a VS Code extension id

Leave a field empty and the component is hidden on that platform.
To add a tool, add a Component and put it in a pack at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass

P = "mingw-w64-ucrt-x86_64-"  # MSYS2 UCRT64 package prefix


@dataclass(frozen=True)
class Component:
    key: str
    name: str
    summary: str
    mono: str                          # two letters shown in the tile
    category: str                      # colours the tile: toolchain, build, editor, quality, github, docs
    winget: str | None = None
    msys: tuple[str, ...] = ()
    brew: tuple[str, ...] = ()
    cask: str | None = None
    mac_special: str | None = None     # "xcode-clt" or "homebrew"
    apt: tuple[str, ...] = ()
    dnf: tuple[str, ...] = ()
    pacman: tuple[str, ...] = ()
    linux_script: str | None = None    # "vscode": adds Microsoft's repository first
    extension: str | None = None       # VS Code extension id
    only: str | None = None            # restrict to one platform
    probe: tuple[str, ...] = ()        # executables or paths proving a program is installed
    requires: tuple[str, ...] = ()     # keys installed first, when they exist on this platform

    def source(self, platform: str, manager: str | None = None) -> tuple[str, tuple[str, ...]] | None:
        """How to install on `platform`: (method, ids), or None if not offered there."""
        if self.only and self.only != platform:
            return None
        if self.extension:
            return "vscode", (self.extension,)
        if platform == "windows":
            if self.winget:
                return "winget", (self.winget,)
            if self.msys:
                return "msys", self.msys
        elif platform == "macos":
            if self.mac_special:
                return "special", (self.mac_special,)
            if self.cask:
                return "cask", (self.cask,)
            if self.brew:
                return "brew", self.brew
        else:
            packages = {"apt": self.apt, "dnf": self.dnf, "pacman": self.pacman}.get(manager or "", ())
            if packages:
                return "linux", packages
            if self.linux_script:
                return "script", (self.linux_script,)
        return None


@dataclass(frozen=True)
class Pack:
    key: str
    title: str
    subtitle: str
    components: tuple[Component, ...]
    recommended: bool = False

    def available(self, platform: str, manager: str | None) -> list[Component]:
        return [c for c in self.components if c.source(platform, manager)]


# ---------------------------------------------------------- prerequisites
MSYS2 = Component(
    "msys2", "MSYS2", "Unix-like environment that provides GCC on Windows", "MS", "toolchain",
    winget="MSYS2.MSYS2", probe=(r"{msys}\usr\bin\pacman.exe",),
)
XCODE_CLT = Component(
    "xcode-clt", "Xcode Command Line Tools", "Apple's base tools: Git, Make and the LLDB debugger", "XC", "toolchain",
    mac_special="xcode-clt",
)
HOMEBREW = Component(
    "homebrew", "Homebrew", "The macOS package manager that installs everything else", "HB", "toolchain",
    mac_special="homebrew", requires=("xcode-clt",),
)

# --------------------------------------------------------------- classic
GCC = Component(
    "gcc", "GCC (gcc, g++)", "The GNU C and C++ compiler", "GC", "toolchain",
    msys=(P + "gcc",), brew=("gcc",), apt=("build-essential",), dnf=("gcc", "gcc-c++"), pacman=("gcc",),
    requires=("msys2", "homebrew"),
)
GDB = Component(
    "gdb", "GDB", "Debugger: breakpoints, stepping, inspecting variables", "GD", "toolchain",
    msys=(P + "gdb",), apt=("gdb",), dnf=("gdb",), pacman=("gdb",),   # macOS uses LLDB from Xcode tools
    requires=("msys2",),
)
CMAKE = Component(
    "cmake", "CMake + Ninja", "Build system generator and the fast build tool it drives", "CM", "build",
    msys=(P + "cmake", P + "ninja"), brew=("cmake", "ninja"),
    apt=("cmake", "ninja-build"), dnf=("cmake", "ninja-build"), pacman=("cmake", "ninja"),
    requires=("msys2", "homebrew"),
)
MAKE = Component(
    "make", "GNU Make", "Classic build tool, for Makefile-based projects", "MK", "build",
    msys=(P + "make",), apt=("make",), dnf=("make",), pacman=("make",),  # macOS: comes with Xcode tools
    requires=("msys2",),
)
GIT = Component(
    "git", "Git", "Version control, needed to push to GitHub", "GI", "github",
    winget="Git.Git", brew=("git",), apt=("git",), dnf=("git",), pacman=("git",),
    probe=("git", r"%ProgramFiles%\Git\cmd\git.exe"), requires=("homebrew",),
)
VSCODE = Component(
    "vscode", "Visual Studio Code", "Editor", "VS", "editor",
    winget="Microsoft.VisualStudioCode", cask="visual-studio-code", linux_script="vscode",
    probe=("code", r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
           r"%ProgramFiles%\Microsoft VS Code\Code.exe", "/Applications/Visual Studio Code.app"),
    requires=("homebrew",),
)
EXT_CPPTOOLS = Component(
    "ext-cpptools", "C/C++ extension", "IntelliSense and debugging in VS Code", "C+", "editor",
    extension="ms-vscode.cpptools", requires=("vscode",),
)
EXT_CMAKE = Component(
    "ext-cmake", "CMake Tools extension", "Configure, build and run CMake projects from VS Code", "CT", "editor",
    extension="ms-vscode.cmake-tools", requires=("vscode",),
)
EXT_CODELLDB = Component(
    "ext-codelldb", "CodeLLDB extension", "Reliable LLDB debugging on macOS", "LL", "editor",
    extension="vadimcn.vscode-lldb", only="macos", requires=("vscode",),
)

# --------------------------------------------------------------- quality
CLANG_TOOLS = Component(
    "clang-tools", "clang-format, clang-tidy, clangd", "Formatter, linter and a fast language server", "CL", "quality",
    msys=(P + "clang-tools-extra",), brew=("llvm",),
    apt=("clang-format", "clang-tidy", "clangd"), dnf=("clang-tools-extra",), pacman=("clang",),
    requires=("msys2", "homebrew"),
)
CPPCHECK = Component(
    "cppcheck", "Cppcheck", "Static analyser that finds bugs without running the code", "CC", "quality",
    msys=(P + "cppcheck",), brew=("cppcheck",), apt=("cppcheck",), dnf=("cppcheck",), pacman=("cppcheck",),
    requires=("msys2", "homebrew"),
)
CATCH2 = Component(
    "catch2", "Catch2", "C++ unit-testing framework", "C2", "quality",
    msys=(P + "catch",), brew=("catch2",), apt=("catch2",), dnf=("catch2-devel",), pacman=("catch2",),
    requires=("msys2", "homebrew"),
)
GTEST = Component(
    "gtest", "GoogleTest", "Google's C++ unit-testing framework", "GT", "quality",
    msys=(P + "gtest",), brew=("googletest",), apt=("libgtest-dev",), dnf=("gtest-devel",), pacman=("gtest",),
    requires=("msys2", "homebrew"),
)
EXT_CLANGD = Component(
    "ext-clangd", "clangd extension", "Faster, more accurate completion than the default IntelliSense", "CD", "quality",
    extension="llvm-vs-code-extensions.vscode-clangd", requires=("vscode",),
)
EXT_ERRORLENS = Component(
    "ext-errorlens", "Error Lens extension", "Shows compiler errors on the line itself", "EL", "quality",
    extension="usernamehw.errorlens", requires=("vscode",),
)

# ---------------------------------------------------------------- github
EXT_PR = Component(
    "ext-github-pr", "GitHub Pull Requests extension", "Review issues and pull requests inside VS Code", "PR", "github",
    extension="github.vscode-pull-request-github", requires=("vscode",),
)
EXT_ACTIONS = Component(
    "ext-github-actions", "GitHub Actions extension", "Edit and watch CI workflows", "GA", "github",
    extension="github.vscode-github-actions", requires=("vscode",),
)
EXT_GITLENS = Component(
    "ext-gitlens", "GitLens extension", "Blame, history and branches in the editor", "GL", "github",
    extension="eamodio.gitlens", requires=("vscode",),
)

# ---------------------------------------------------------------- extras
GH = Component(
    "gh", "GitHub CLI", "Sign in, create repositories and pull requests from the terminal", "GH", "github",
    winget="GitHub.cli", brew=("gh",), apt=("gh",), dnf=("gh",), pacman=("github-cli",),
    probe=("gh", r"%ProgramFiles%\GitHub CLI\gh.exe"), requires=("homebrew",),
)
CCACHE = Component(
    "ccache", "ccache", "Caches compilations, so rebuilds are much faster", "CA", "build",
    msys=(P + "ccache",), brew=("ccache",), apt=("ccache",), dnf=("ccache",), pacman=("ccache",),
    requires=("msys2", "homebrew"),
)
DOXYGEN = Component(
    "doxygen", "Doxygen", "Generates documentation from code comments", "DX", "docs",
    msys=(P + "doxygen",), brew=("doxygen",), apt=("doxygen",), dnf=("doxygen",), pacman=("doxygen",),
    requires=("msys2", "homebrew"),
)
BENCHMARK = Component(
    "benchmark", "Google Benchmark", "Measures how fast your functions run", "GB", "quality",
    msys=(P + "benchmark",), brew=("google-benchmark",), apt=("libbenchmark-dev",),
    dnf=("google-benchmark-devel",), pacman=("benchmark",),
    requires=("msys2", "homebrew"),
)
EXT_DOXGEN = Component(
    "ext-doxdocgen", "Doxygen Documentation Generator", "Writes comment skeletons for functions", "DG", "docs",
    extension="cschlosser.doxdocgen", requires=("vscode",),
)
EXT_HEX = Component(
    "ext-hexeditor", "Hex Editor extension", "Look at binary files byte by byte", "HX", "docs",
    extension="ms-vscode.hexeditor", requires=("vscode",),
)


PACKS: tuple[Pack, ...] = (
    Pack(
        "classic", "Classic pack",
        "Everything needed to write, build and debug C and C++ with GCC in VS Code.",
        (MSYS2, XCODE_CLT, HOMEBREW, GCC, GDB, CMAKE, MAKE, GIT, VSCODE, EXT_CPPTOOLS, EXT_CMAKE, EXT_CODELLDB),
        recommended=True,
    ),
    Pack(
        "quality", "Code quality",
        "Formatting, linting, static analysis and unit tests.",
        (CLANG_TOOLS, CPPCHECK, CATCH2, GTEST, EXT_CLANGD, EXT_ERRORLENS),
    ),
    Pack(
        "github", "GitHub in VS Code",
        "Pull requests, CI workflows and history without leaving the editor.",
        (EXT_PR, EXT_ACTIONS, EXT_GITLENS),
    ),
    Pack(
        "extras", "Extras",
        "GitHub CLI, faster rebuilds, documentation and benchmarks.",
        (GH, CCACHE, DOXYGEN, BENCHMARK, EXT_DOXGEN, EXT_HEX),
    ),
)

ALL_COMPONENTS: dict[str, Component] = {c.key: c for p in PACKS for c in p.components}

_METHOD_RANK = {"winget": 0, "special": 0, "cask": 1, "script": 1, "msys": 2, "brew": 2, "linux": 2, "vscode": 3}


def install_order(components: list[Component], platform: str, manager: str | None = None) -> list[Component]:
    """Programs and package managers first, packages next, VS Code extensions last."""
    def rank(c: Component) -> int:
        src = c.source(platform, manager)
        return _METHOD_RANK[src[0]] if src else 9
    return sorted(components, key=rank)
