"""Scans a folder for the launcher's explorer: C, C++ and header files, and which ones can run.

Pure logic, no Qt, so it is easy to test. A source file "can run" when it defines
main(): those are the files F5 can build into a program on their own.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .toolchain import C_EXTENSIONS, CPP_EXTENSIONS

HEADER_EXTENSIONS = {".h", ".hpp", ".hh", ".hxx", ".h++", ".inl", ".ipp", ".tpp"}

# Folders nobody wants to browse: build output, tool caches, virtual environments.
SKIPPED_DIRS = {"build", "dist", "node_modules", "__pycache__", "venv", "out", "bin", "obj"}
SKIPPED_PREFIXES = (".", "cmake-build-")

MAX_FILES = 3000          # a scan stops listing after this many files
MAX_DEPTH = 10            # and does not go deeper than this
MAX_READ = 512 * 1024     # bytes read per source file when looking for main()
READ_BUDGET = 1.5         # seconds spent reading files per scan; the rest is checked next time


def file_kind(path: str | Path) -> str:
    """"c", "cpp", "header" or "other", from the extension."""
    ext = Path(path).suffix.lower()
    if ext in C_EXTENSIONS:
        return "c"
    if ext in CPP_EXTENSIONS:
        return "cpp"
    if ext in HEADER_EXTENSIONS:
        return "header"
    return "other"


# Comments and string or character literals, removed before looking for main(),
# so "// int main()" or puts("int main(") do not count.
_NOISE = re.compile(
    r'//[^\n]*'                          # line comment
    r'|/\*.*?\*/'                        # block comment
    r'|R"([^(\s]{0,16})\(.*?\)\1"'       # C++ raw string R"x(...)x"
    r'|"(?:\\.|[^"\\\n])*"'              # string literal
    r"|'(?:\\.|[^'\\\n])*'",             # character literal
    re.DOTALL,
)
# A definition of main: "int main(", "auto main(", "void main(" (beginners' code),
# with "main" not part of a longer name and not a member (x.main, x->main, X::main).
_MAIN = re.compile(r"(?<![\w.:>])(?:int|auto|void)\s+main\s*\([^;{]*\)\s*(?:->\s*int\s*)?\{")


def has_main(text: str) -> bool:
    return _MAIN.search(_NOISE.sub(" ", text)) is not None


@dataclass
class Node:
    name: str
    path: Path
    kind: str                      # "dir", "c", "cpp", "header" or "other"
    runnable: bool = False
    children: list["Node"] = field(default_factory=list)

    def files(self):
        """Every file under this node, depth first."""
        for child in self.children:
            if child.kind == "dir":
                yield from child.files()
            else:
                yield child


@dataclass
class Scan:
    root: Node
    truncated: bool = False        # MAX_FILES was reached
    unchecked: int = 0             # sources not read for main() because of READ_BUDGET

    def counts(self) -> dict[str, int]:
        out = {"c": 0, "cpp": 0, "header": 0, "other": 0, "runnable": 0}
        for f in self.root.files():
            out[f.kind] += 1
            out["runnable"] += f.runnable
        return out

    def first_runnable(self) -> Path | None:
        return next((f.path for f in self.root.files() if f.runnable), None)

    def summary(self) -> str:
        c = self.counts()
        parts = [f"{c['c']} C", f"{c['cpp']} C++", f"{c['header']} header" + ("s" if c["header"] != 1 else "")]
        text = ", ".join(parts) + f"  ·  {c['runnable']} can run"
        if self.truncated:
            text += f"  ·  first {MAX_FILES} files only"
        return text


def skip_dir(name: str) -> bool:
    return name.lower() in SKIPPED_DIRS or name.startswith(SKIPPED_PREFIXES)


class Scanner:
    """Scans folders and remembers which files define main(), keyed by size and date,
    so a rescan only reads the files that changed."""

    def __init__(self):
        self._cache: dict[str, tuple[int, int, bool]] = {}

    def runnable(self, path: Path, deadline: float | None = None) -> bool | None:
        """True or False, or None when the time budget ran out before the file was read."""
        try:
            st = path.stat()
        except OSError:
            return False
        key = str(path)
        cached = self._cache.get(key)
        if cached and cached[:2] == (st.st_size, st.st_mtime_ns):
            return cached[2]
        if deadline is not None and time.perf_counter() > deadline:
            return None
        try:
            with open(path, "rb") as fh:
                text = fh.read(MAX_READ).decode("utf-8", "replace")
        except OSError:
            return False
        result = has_main(text)
        self._cache[key] = (st.st_size, st.st_mtime_ns, result)
        return result

    def scan(self, folder: str | Path, all_files: bool = False) -> Scan:
        folder = Path(folder).resolve()
        root = Node(folder.name or str(folder), folder, "dir")
        result = Scan(root)
        deadline = time.perf_counter() + READ_BUDGET
        count = 0

        def walk(node: Node, depth: int) -> None:
            nonlocal count
            try:
                entries = list(os.scandir(node.path))
            except OSError:
                return
            dirs, files = [], []
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth < MAX_DEPTH and not skip_dir(e.name):
                            dirs.append(e)
                    elif e.is_file() and not e.name.startswith("."):
                        files.append(e)
                except OSError:
                    continue
            for e in sorted(dirs, key=lambda e: e.name.lower()):
                if count >= MAX_FILES:
                    result.truncated = True
                    return
                child = Node(e.name, Path(e.path), "dir")
                walk(child, depth + 1)
                if child.children:                       # hide folders with nothing to show
                    node.children.append(child)
            for e in sorted(files, key=lambda e: e.name.lower()):
                kind = file_kind(e.name)
                if kind == "other" and not all_files:
                    continue
                if count >= MAX_FILES:
                    result.truncated = True
                    return
                count += 1
                runnable = False
                if kind in ("c", "cpp"):
                    found = self.runnable(Path(e.path), deadline)
                    if found is None:
                        result.unchecked += 1
                    runnable = bool(found)
                node.children.append(Node(e.name, Path(e.path), kind, runnable))

        walk(root, 0)
        return result


def watched_dirs(scan: Scan, limit: int = 200) -> list[str]:
    """The folder and its shown subfolders, for a file-system watcher."""
    out = [str(scan.root.path)]

    def walk(node: Node) -> None:
        for child in node.children:
            if child.kind == "dir" and len(out) < limit:
                out.append(str(child.path))
                walk(child)
    walk(scan.root)
    return out
