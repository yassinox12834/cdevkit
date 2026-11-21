"""Generates a ready-to-build CMake project for C or C++ with VS Code configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import system

# CMake's C_STANDARD has no 89 value: 90 is the same language.
_CMAKE_STD = {
    "c89": "90", "c99": "99", "c11": "11", "c17": "17", "c23": "23",
    "c++98": "98", "c++11": "11", "c++14": "14", "c++17": "17",
    "c++20": "20", "c++23": "23", "c++26": "26",
}

CLANG_FORMAT = """\
BasedOnStyle: LLVM
IndentWidth: 4
ColumnLimit: 100
PointerAlignment: Left
AllowShortFunctionsOnASingleLine: Empty
"""

GITIGNORE = """\
build/
.cache/
compile_commands.json
*.exe
*.o
*.obj
"""

MAIN_C = """\
#include <stdio.h>

int main(void) {
    printf("Hello from C!\\n");
    return 0;
}
"""

MAIN_CPP = """\
#include <iostream>

int main() {
    std::cout << "Hello from C++!\\n";
    return 0;
}
"""


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_-")
    return cleaned or "app"


def _posix(p: Path) -> str:
    return str(p).replace("\\", "/")


def compiler_names() -> tuple[str, str]:
    """Bare names, not full paths, so the project still builds on other machines.
    On macOS these are the versioned Homebrew names such as gcc-15."""
    from .toolchain import find_compiler
    names = []
    for lang, default in (("c", "gcc"), ("cpp", "g++")):
        found = find_compiler(lang)
        names.append(Path(found).stem if found and system.IS_MAC else default)
    return names[0], names[1]


def debugger_settings() -> dict:
    if system.IS_MAC:
        return {"MIMode": "lldb"}            # GDB does not run on Apple Silicon
    if system.IS_WINDOWS:
        return {"MIMode": "gdb", "miDebuggerPath": _posix(system.UCRT_BIN / "gdb.exe")}
    return {"MIMode": "gdb", "miDebuggerPath": system.find_tool("gdb") or "/usr/bin/gdb"}


def render(name: str, language: str, standard: str) -> dict[str, str]:
    """Return {relative path: file content} for the new project."""
    name = safe_name(name)
    is_c = language == "c"
    lang = "C" if is_c else "CXX"
    ext = "c" if is_c else "cpp"
    std_num = _CMAKE_STD.get(standard, "17" if is_c else "20")
    exe = name + (".exe" if system.IS_WINDOWS else "")
    cc, cxx = compiler_names()

    cmakelists = f"""\
cmake_minimum_required(VERSION 3.21)
project({name} LANGUAGES {lang})

set(CMAKE_{lang}_STANDARD {std_num})
set(CMAKE_{lang}_STANDARD_REQUIRED ON)
set(CMAKE_{lang}_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_executable({name} src/main.{ext})
target_compile_options({name} PRIVATE -Wall -Wextra -Wpedantic)
"""

    compilers = {"CMAKE_C_COMPILER": cc, "CMAKE_CXX_COMPILER": cxx}
    presets = {
        "version": 3,
        "configurePresets": [
            {
                "name": "base", "hidden": True, "generator": "Ninja",
                "binaryDir": "${sourceDir}/build/${presetName}",
                "cacheVariables": compilers,
            },
            {"name": "debug", "inherits": "base", "displayName": "Debug",
             "cacheVariables": {"CMAKE_BUILD_TYPE": "Debug"}},
            {"name": "release", "inherits": "base", "displayName": "Release",
             "cacheVariables": {"CMAKE_BUILD_TYPE": "Release"}},
        ],
        "buildPresets": [
            {"name": "debug", "configurePreset": "debug"},
            {"name": "release", "configurePreset": "release"},
        ],
    }

    tasks = {
        "version": "2.0.0",
        "tasks": [
            {"label": "configure (debug)", "type": "shell", "command": "cmake --preset debug",
             "problemMatcher": []},
            {"label": "build (debug)", "type": "shell", "command": "cmake --build --preset debug",
             "dependsOn": "configure (debug)", "group": {"kind": "build", "isDefault": True},
             "problemMatcher": ["$gcc"]},
        ],
    }

    launch = {
        "version": "0.2.0",
        "configurations": [{
            "name": "Debug (GDB)", "type": "cppdbg", "request": "launch",
            "program": "${workspaceFolder}/build/debug/" + exe,
            "args": [], "cwd": "${workspaceFolder}", "stopAtEntry": False,
            "externalConsole": False, "preLaunchTask": "build (debug)",
            **debugger_settings(),
            "setupCommands": [{"description": "Pretty printing", "text": "-enable-pretty-printing",
                               "ignoreFailures": True}],
        }],
    }

    vscode_settings = {"cmake.useCMakePresets": "always", "cmake.configureOnOpen": True}

    readme = f"""\
# {name}

A {"C" if is_c else "C++"} project ({standard}) built with CMake, Ninja and GCC.

## Build and run

```
cmake --preset debug
cmake --build --preset debug
./build/debug/{exe}
```

In VS Code: press `Ctrl+Shift+B` to build, `F5` to debug.
"""

    return {
        "CMakeLists.txt": cmakelists,
        "CMakePresets.json": json.dumps(presets, indent=2) + "\n",
        f"src/main.{ext}": MAIN_C if is_c else MAIN_CPP,
        ".vscode/tasks.json": json.dumps(tasks, indent=2) + "\n",
        ".vscode/launch.json": json.dumps(launch, indent=2) + "\n",
        ".vscode/settings.json": json.dumps(vscode_settings, indent=2) + "\n",
        ".clang-format": CLANG_FORMAT,
        ".gitignore": GITIGNORE,
        "README.md": readme,
    }


def create_project(parent: Path, name: str, language: str, standard: str, log: system.Log,
                   git_init: bool = True) -> Path | None:
    dest = parent / safe_name(name)
    if dest.exists() and any(dest.iterdir()):
        log(f"error: {dest} already exists and is not empty. Pick another name.")
        return None
    for rel, content in render(name, language, standard).items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        log(f"  created {rel}")
    if git_init:
        git = system.find_tool("git")
        if git:
            system.run_stream([git, "init", "-b", "main"], log, cwd=dest)
        else:
            log("Git not found: skipped 'git init'.")
    log(f"✓ Project created in {dest}")
    return dest
