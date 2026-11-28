"""C/C++ DevKit Launcher: pick a .c or .cpp file, choose the standard, build and run with GCC.

Run with launcher.bat (Windows), launcher.command (macOS), ./launcher.sh (Linux), or:
    python launcher_app.py [file or folder]
Shortcuts: Ctrl+O open a file, Ctrl+Shift+O open a folder, Ctrl+B build, F5 run (rebuilds if needed),
Shift+F5 stop.
"""

from __future__ import annotations

import codecs
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMainWindow, QMenu, QPlainTextEdit, QProgressBar,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from devkit import project, system, toolchain
from devkit import qt as ui

FILE_FILTER = "C and C++ sources (*.c *.cpp *.cc *.cxx *.c++);;C sources (*.c);;C++ sources (*.cpp *.cc *.cxx *.c++);;All files (*)"
LANG_LABEL = {"c": "C", "cpp": "C++"}
LABEL_LANG = {v: k for k, v in LANG_LABEL.items()}
PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_TIPS = {
    "c": "C source", "cpp": "C++ source", "header": "Header: included by sources, not run on its own",
    "other": "Not a C or C++ file",
}


class Explorer(QFrame):
    """The open folder as a tree, like VS Code's explorer.

    C, C++ and header files get their own icon; a green dot marks the files that
    define main(), the ones F5 can build and run. The tree follows the disk: a
    watcher rescans when files are added, removed or renamed, and the window
    rescans when it comes back to the front, which catches edits made in VS Code.

    Scans run on a worker thread, so a big folder never freezes the window: the
    UI thread only swaps in the finished result. One scan runs at a time; a
    request made meanwhile is remembered and runs straight after."""

    POLL_MS = 25

    def __init__(self, window: "LauncherWindow"):
        super().__init__()
        self.window = window
        self.setObjectName("card")
        self.setFixedWidth(270)
        self.folder: Path | None = None
        self.scanner = project.Scanner()
        self.scan: project.Scan | None = None
        self._items: dict[str, QTreeWidgetItem] = {}
        self._gen = 0                                 # bumped on open/close: older scan results are dropped
        self.scanning = False
        self._again = False
        self._result = None
        self._result_lock = threading.Lock()
        self._callbacks: list = []
        self.last_scan = 0.0
        self._poll = QTimer(self)
        self._poll.setInterval(self.POLL_MS)
        self._poll.timeout.connect(self._collect)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 12, 8, 10)
        lay.setSpacing(6)
        self.b_refresh = ui.button("Refresh", self.refresh, flat=True)
        self.b_refresh.setToolTip("Scan the folder again")
        self.b_close = ui.button("Close", self.close_folder, flat=True)
        lay.addWidget(ui.row(ui.label("EXPLORER", "caps"), "stretch", self.b_refresh, self.b_close,
                             spacing=0, stretch_end=False))
        self.title = ui.label("No folder open", "heading", wrap=True)
        lay.addWidget(self.title)

        self.tree = QTreeWidget()
        self.tree.setObjectName("explorer")
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        ui.smooth_scroll(self.tree)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.currentItemChanged.connect(lambda item, _prev: self._chosen(item))   # click or arrow keys
        self.tree.itemActivated.connect(self._activated)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree, 1)

        self.empty = QWidget()
        empty_lay = QVBoxLayout(self.empty)
        empty_lay.setContentsMargins(0, 8, 0, 0)
        empty_lay.addWidget(ui.label("Open a folder to see its C and C++ files, with the ones you can "
                                     "run marked by a green dot.", "faint", wrap=True))
        empty_lay.addWidget(ui.row(ui.button("Open folder...", window.browse_folder, primary=True)))
        empty_lay.addStretch(1)
        lay.addWidget(self.empty, 1)

        self.all_files = QCheckBox("Show other files")
        self.all_files.setChecked(bool(window.settings.get("explorer_all_files", False)))
        self.all_files.toggled.connect(self._all_files_toggled)
        lay.addWidget(self.all_files)
        legend = ui.row(ui.Dot("ok"), ui.label("defines main(): F5 runs it", "faint"), spacing=4)
        lay.addWidget(legend)
        self.summary = ui.label("", "faint", wrap=True)
        lay.addWidget(self.summary)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._debounce.start())
        self._debounce = QTimer(self)                # a "git checkout" fires dozens of events: scan once
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.refresh)
        self._show_tree(False)

    # ----------------------------------------------------------- folder
    def _show_tree(self, shown: bool) -> None:
        self.tree.setVisible(shown)
        self.empty.setVisible(not shown)
        for w in (self.b_refresh, self.b_close, self.summary):
            w.setVisible(shown)

    def open(self, folder: Path, on_done=None) -> None:
        """Show `folder`. The tree fills in when the first scan finishes; on_done runs then."""
        self.folder = Path(folder).resolve()
        self._gen += 1
        self._callbacks.clear()
        self.title.setText(self.folder.name or str(self.folder))
        self.title.setToolTip(str(self.folder))
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.blockSignals(False)
        self._items.clear()
        self.scan = None
        self._show_tree(True)
        self.summary.setText("Scanning...")
        self.refresh(on_done)

    def close_folder(self) -> None:
        self.folder = None
        self._gen += 1
        self._callbacks.clear()
        self.scan = None
        self.tree.clear()
        self._items.clear()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.title.setText("No folder open")
        self.title.setToolTip("")
        self._show_tree(False)
        self.window.settings.set("folder", None)

    def refresh(self, on_done=None) -> None:
        """Scan the folder again, in the background. Cheap to call often."""
        if not self.folder:
            return
        if on_done:
            self._callbacks.append(on_done)
        if self.scanning:
            self._again = True
            return
        self._start_scan()

    def _start_scan(self) -> None:
        folder, all_files, gen = self.folder, self.all_files.isChecked(), self._gen
        self.scanning, self._again = True, False
        scanner = self.scanner

        def work():
            try:
                outcome = ("ok", scanner.scan(folder, all_files)) if folder.is_dir() else ("gone", None)
            except Exception as exc:  # noqa: BLE001  (shown in the console, never a crash)
                outcome = ("error", exc)
            with self._result_lock:
                self._result = (gen, outcome)

        threading.Thread(target=work, daemon=True).start()
        self._poll.start()

    def _collect(self) -> None:
        with self._result_lock:
            result, self._result = self._result, None
        if result is None:
            return
        self._poll.stop()
        self.scanning = False
        self.last_scan = time.monotonic()
        gen, (status, value) = result
        if gen != self._gen:                          # the folder changed while scanning
            if self.folder:
                self._start_scan()
            return
        if status == "gone":
            self.window.console.write(f"error: {self.folder} no longer exists.")
            self.close_folder()
            return
        if status == "error":
            self.window.console.write(f"error: could not scan {self.folder}: {value}")
        else:
            self._apply(value)
        callbacks, self._callbacks = self._callbacks, []
        for cb in callbacks:
            cb()
        if self._again:
            self._start_scan()
        elif status == "ok" and value.unchecked:      # huge folder: finish reading for main() shortly
            QTimer.singleShot(200, self.refresh)

    def _apply(self, scan: project.Scan) -> None:
        if self.scan is None or self._shape(scan) != self._shape(self.scan):
            self._rebuild(scan)
        self.scan = scan
        self.summary.setText(scan.summary())
        old = set(self.watcher.directories())
        new = set(project.watched_dirs(scan))
        if old - new:
            self.watcher.removePaths(list(old - new))
        if new - old:
            self.watcher.addPaths(list(new - old))

    @staticmethod
    def _shape(scan: project.Scan) -> list[tuple[str, str, bool]]:
        def walk(node):
            for c in node.children:
                yield (str(c.path), c.kind, c.runnable)
                if c.kind == "dir":
                    yield from walk(c)
        return list(walk(scan.root))

    def _rebuild(self, scan: project.Scan) -> None:
        """Redraw the tree, keeping which folders were collapsed and where it was scrolled."""
        collapsed = {p for p, item in self._items.items() if item.childCount() and not item.isExpanded()}
        scroll = self.tree.verticalScrollBar().value()
        self.tree.setUpdatesEnabled(False)            # one repaint at the end, no flicker
        self.tree.blockSignals(True)                  # clearing must not count as choosing a file
        self.tree.clear()
        self._items.clear()

        def add(parent, node: project.Node) -> None:
            for child in node.children:
                item = QTreeWidgetItem(parent, [child.name])
                item.setIcon(0, ui.file_icon(child.kind, child.runnable))
                item.setData(0, PATH_ROLE, str(child.path))
                if child.kind == "dir":
                    item.setToolTip(0, str(child.path))
                    add(item, child)
                    item.setExpanded(str(child.path) not in collapsed)
                else:
                    tip = KIND_TIPS[child.kind]
                    if child.runnable:
                        tip += "  ·  defines main(): F5 builds and runs it"
                    item.setToolTip(0, f"{tip}\n{child.path}")
                    if child.kind == "other":
                        item.setForeground(0, QColor(ui.FAINT))
                self._items[str(child.path)] = item

        add(self.tree.invisibleRootItem(), scan.root)
        self.tree.blockSignals(False)
        self.tree.setUpdatesEnabled(True)
        self.tree.verticalScrollBar().setValue(scroll)
        self.select(self.window.file, scroll_to=False)

    def _all_files_toggled(self, on: bool) -> None:
        self.window.settings.set("explorer_all_files", on)
        self.window.save_soon()
        self._gen += 1                                # a scan of the old kind is now stale
        self.scan = None                              # force a redraw
        self.refresh()

    def select(self, path: Path | None, scroll_to: bool = True) -> None:
        """Highlight the launcher's current file, if it is in this folder."""
        item = self._items.get(str(path)) if path else None
        self.tree.blockSignals(True)
        if item:
            if self.tree.currentItem() is not item:
                self.tree.setCurrentItem(item)
            if scroll_to:
                self.tree.scrollToItem(item)
        else:
            self.tree.clearSelection()
        self.tree.blockSignals(False)

    def contains(self, path: Path | None) -> bool:
        return bool(path and str(path) in self._items)

    # ------------------------------------------------------ interaction
    @staticmethod
    def _path(item: QTreeWidgetItem | None) -> Path | None:
        return Path(item.data(0, PATH_ROLE)) if item else None

    def _chosen(self, item: QTreeWidgetItem | None) -> None:
        path = self._path(item)
        if path and project.file_kind(path) in ("c", "cpp") and path != self.window.file:
            self.window.set_file(path)

    def _activated(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        """Double-click or Enter: open files in VS Code, as VS Code's own explorer does."""
        path = self._path(item)
        if path and path.is_file():
            self.window.open_in_vscode(path)

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        path = self._path(item)
        if not path:
            return
        menu = QMenu(self)
        kind = "dir" if path.is_dir() else project.file_kind(path)
        if kind in ("c", "cpp"):
            busy = self.window.tasks.busy
            mode = self.window.mode()
            run = menu.addAction(f"{toolchain.MODE_TEXT[mode]}   F5",
                                 lambda: (self.window.set_file(path), self.window.run()))
            run.setEnabled(not busy)
            other = menu.addMenu("Run as")
            other.setEnabled(not busy)
            for key in toolchain.MODE_KEYS:
                other.addAction(toolchain.MODE_TEXT[key],
                                lambda k=key: (self.window.set_file(path), self.window.run(k)))
            build = menu.addAction("Build   Ctrl+B", lambda: (self.window.set_file(path), self.window.build()))
            build.setEnabled(not busy)
            menu.addSeparator()
        if kind != "dir":
            menu.addAction("Open in VS Code", lambda: self.window.open_in_vscode(path))
        menu.addAction("Show in file manager", lambda: system.open_folder(path if kind == "dir" else path.parent))
        menu.exec(self.tree.viewport().mapToGlobal(pos))


@dataclass
class Plan:
    """Everything one build needs, fixed when the user presses the button: choosing
    another file while it compiles must not change where it compiles."""
    cmd: list[str]
    out: Path
    sources: list[Path]
    opts: toolchain.BuildOptions
    file: Path

    @property
    def cwd(self) -> Path:
        return self.file.parent


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("C/C++ DevKit Launcher")
        self.resize(1440, 820)
        self.setMinimumSize(1180, 600)
        self.settings = system.Settings("launcher")
        self.proc: subprocess.Popen | None = None
        self.file: Path | None = None
        self.gcc_major = 0
        self.gcc_version: str | None = None
        self._compilers: dict[str, str | None] = {}   # found once, not on every keystroke
        s = self.settings
        self.std_by_lang: dict[str, str] = dict(toolchain.DEFAULT_STANDARD, **s.get("standards", {}))
        self.last_output: Path | None = None
        self._save_timer = QTimer(self)               # many quick changes, one write to disk
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)
        outer.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(14)
        self.explorer = Explorer(self)
        body.addWidget(self.explorer)
        body.addWidget(self._build_panel())
        body.addWidget(self._build_output(), 1)
        outer.addLayout(body, 1)

        self.tasks = ui.TaskRunner(self.console)
        self.tasks.busy_changed.connect(self._on_busy)

        for key, slot in (("Ctrl+O", self.browse), ("Ctrl+Shift+O", self.browse_folder), ("Ctrl+B", self.build),
                          ("F5", self.run), ("Shift+F5", self.stop)):
            QShortcut(QKeySequence(key), self, slot)

        # Any option change updates the command preview.
        for box in self.checks.values():
            box.toggled.connect(self._update_preview)
        self.lang.changed.connect(self._lang_changed)
        self.std.currentTextChanged.connect(self._std_changed)
        self.opt.changed.connect(lambda _: self._update_preview())
        self.extra.textChanged.connect(self._update_preview)
        self.mode_box.currentIndexChanged.connect(self._mode_changed)

        last = s.get("file")
        if last and Path(last).is_file():
            self.set_file(Path(last))
        else:
            self._update_preview()
        folder = s.get("folder")
        if folder and Path(folder).is_dir():
            self.explorer.open(Path(folder))
        self._mode_changed()
        self.console.write("Open a folder (Ctrl+Shift+O) or a single .c or .cpp file (Ctrl+O), "
                           "then press F5 to build and run.", "muted")
        self.tasks.run("Looking for GCC...", lambda: toolchain.compiler_info("cpp"), self._show_compiler)

    # ------------------------------------------------------------ layout
    def _build_header(self) -> QWidget:
        self.compiler_pill = ui.label("GCC: checking...", "pill")
        self.b_build = ui.button("Build   Ctrl+B", self.build)
        self.b_run = ui.button("Run   F5", lambda: self.run(), primary=True)
        self.b_stop = ui.button("Stop", self.stop)
        self.b_stop.setEnabled(False)
        return ui.row(ui.label("Launcher", "title"), self.compiler_pill, "stretch",
                      self.b_build, self.b_run, self.b_stop, spacing=10, stretch_end=False)

    def _caps(self, lay: QVBoxLayout, text: str) -> None:
        lay.addSpacing(10)
        lay.addWidget(ui.label(text.upper(), "caps"))

    def _build_panel(self) -> QWidget:
        s = self.settings
        frame, lay = ui.card()
        lay.setSpacing(6)

        self._caps(lay, "Source file")
        self.file_label = ui.label("No file selected", "faint", wrap=True)
        self.file_dir = ui.label("", "faint", wrap=True)
        lay.addWidget(self.file_label)
        lay.addWidget(self.file_dir)
        self.recent_btn = ui.button("Recent")
        self.recent_menu = QMenu(self)
        self.recent_btn.setMenu(self.recent_menu)
        lay.addWidget(ui.row(ui.button("Open file...", self.browse), ui.button("Open folder...", self.browse_folder)))
        lay.addWidget(ui.row(self.recent_btn, ui.button("Edit in VS Code", self.edit_in_vscode)))
        self._fill_recent()

        self._caps(lay, "Language and standard")
        lang = s.get("language", "cpp")
        self.lang = ui.Segmented(["C", "C++"], LANG_LABEL[lang])
        self.std = ui.ComboBox()
        self.std.addItems(toolchain.STANDARDS[lang])
        self.std.setCurrentText(self.std_by_lang[lang])
        self.std.setMinimumWidth(110)
        lay.addWidget(ui.row(self.lang, self.std, spacing=10))

        self._caps(lay, "Optimisation")
        self.opt = ui.Segmented(toolchain.OPTIMISATIONS, s.get("optimisation", "-O0"))
        lay.addWidget(ui.row(self.opt))
        lay.addWidget(ui.label("-O0 for debugging, -O2 for speed.", "faint"))

        self.checks: dict[str, QCheckBox] = {}

        def check(key: str, text: str, default: bool, tip: str = "") -> None:
            box = QCheckBox(text)
            box.setChecked(bool(s.get(key, default)))
            if tip:
                box.setToolTip(tip)
            self.checks[key] = box
            lay.addWidget(box)

        self._caps(lay, "Compiler checks")
        check("warnings", "Warnings  -Wall -Wextra -Wpedantic", True)
        check("werror", "Treat warnings as errors  -Werror", False)
        check("debug", "Debug information  -g", True)
        check("ub_trap", "Stop on undefined behaviour", False,
              "Overflow, bad shifts and similar bugs stop the program instead of giving wrong results.")
        check("gnu", "GNU extensions (gnu17 instead of c17)", False)

        self._caps(lay, "Build")
        check("whole_folder", "Compile every file in the folder", False)
        if not system.IS_MAC:                     # macOS does not allow fully static executables
            check("static", "Static link (exe runs anywhere)", False)
        lay.addWidget(ui.label("Extra flags", "muted"))
        self.extra = QLineEdit(s.get("extra_flags", ""))
        self.extra.setPlaceholderText("-DDEBUG -Iinclude")
        lay.addWidget(self.extra)

        self._caps(lay, "Run")
        lay.addWidget(ui.label("What F5 does", "muted"))
        self.mode_box = ui.ComboBox()
        for key in toolchain.MODE_KEYS:
            self.mode_box.addItem(toolchain.MODE_TEXT[key], key)
        saved = s.get("run_mode") or ("terminal" if s.get("external") else "here")   # 1.3.0 had a checkbox
        self.mode_box.setCurrentIndex(toolchain.MODE_KEYS.index(saved) if saved in toolchain.MODE_KEYS else 0)
        lay.addWidget(self.mode_box)
        self.mode_help = ui.label("", "faint", wrap=True)
        lay.addWidget(self.mode_help)

        lay.addWidget(ui.label("Arguments", "muted"))
        self.args = QLineEdit(s.get("args", ""))
        self.args.setPlaceholderText("arg1 arg2")
        lay.addWidget(self.args)

        self.stdin_label = ui.label("Input (sent to stdin)", "muted")
        lay.addWidget(self.stdin_label)
        self.stdin_box = QPlainTextEdit()
        self.stdin_box.setFont(ui.mono_font())
        self.stdin_box.setFixedHeight(70)
        self.stdin_box.setPlaceholderText("4 8 15 16 23 42")
        lay.addWidget(self.stdin_box)

        self.expected_label = ui.label("Expected output", "muted")
        lay.addWidget(self.expected_label)
        self.expected_box = QPlainTextEdit()
        self.expected_box.setFont(ui.mono_font())
        self.expected_box.setFixedHeight(70)
        self.expected_box.setPlaceholderText("Empty: uses <name>.out or <name>.ans next to the file")
        lay.addWidget(self.expected_box)

        self.runs_label = ui.label("Number of runs", "muted")
        self.runs_box = ui.SpinBox()
        self.runs_box.setRange(2, 1000)
        self.runs_box.setValue(int(s.get("bench_runs", 10)))
        self.runs_box.setFixedWidth(90)
        self.runs_row = ui.row(self.runs_label, self.runs_box, spacing=10)
        lay.addWidget(self.runs_row)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().setSingleStep(24)
        scroll.setWidget(frame)
        scroll.setFixedWidth(370)
        return scroll

    def _build_output(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        prev, prev_lay = ui.card()
        prev_lay.setContentsMargins(14, 10, 14, 12)
        prev_lay.addWidget(ui.label("COMMAND", "caps"))
        self.preview = ui.label("", "muted", wrap=True)
        self.preview.setFont(ui.mono_font(9))
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        prev_lay.addWidget(self.preview)
        lay.addWidget(prev)

        out_frame, self.console = ui.console_panel("Output  (double-click an error to open it)")
        lay.addWidget(out_frame, 1)

        self.status_dot = ui.Dot()
        self.status_label = ui.label("Ready", "muted")
        self.progress = QProgressBar()                # moving bar while something runs
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(120)
        self.progress.hide()
        self.b_show = ui.button("Show executable", self.show_output, flat=True)
        self.b_show.setToolTip("Open the folder that holds the executable just made")
        self.b_show.hide()
        lay.addWidget(ui.row(self.status_dot, self.status_label, self.progress, self.b_show, spacing=6))
        return w

    # ------------------------------------------------------------ state
    def _show_compiler(self, info) -> None:
        self._compilers.clear()
        if not isinstance(info, toolchain.CompilerInfo) or not info.path:
            self._pill("GCC not found: install the Classic pack", ui.ERR)
        elif info.is_clang:
            self._pill("Only Apple Clang found: install GCC from the Classic pack", ui.WARN)
        else:
            self.gcc_version = info.version
            self.gcc_major = toolchain.gcc_major(info.version)
            self._pill(f"GCC {info.version}", ui.OK)
            self._lang_changed(self.lang.value())   # hide standards this GCC cannot compile
        self._update_preview()

    def _pill(self, text: str, color: str) -> None:
        self.compiler_pill.setText(text)
        self.compiler_pill.setStyleSheet(f"color: {color};")

    def _lang(self) -> str:
        return LABEL_LANG.get(self.lang.value(), "cpp")

    def _lang_changed(self, value: str) -> None:
        lang = LABEL_LANG[value]
        allowed = toolchain.supported_standards(lang, self.gcc_major)
        wanted = self.std_by_lang[lang]
        self.std.blockSignals(True)
        self.std.clear()
        self.std.addItems(allowed)
        self.std.setCurrentText(wanted if wanted in allowed else toolchain.DEFAULT_STANDARD[lang])
        self.std.blockSignals(False)
        self._update_preview()

    def _std_changed(self, value: str) -> None:
        if value:
            self.std_by_lang[self._lang()] = value
        self._update_preview()

    def _checked(self, key: str) -> bool:
        box = self.checks.get(key)
        return bool(box and box.isChecked())

    def options(self) -> toolchain.BuildOptions:
        return toolchain.BuildOptions(
            language=self._lang(), standard=self.std.currentText(), optimisation=self.opt.value(),
            warnings=self._checked("warnings"), debug=self._checked("debug"), werror=self._checked("werror"),
            ub_trap=self._checked("ub_trap"), static=self._checked("static"), gnu=self._checked("gnu"),
            extra_flags=self.extra.text(), gcc_major=self.gcc_major,
        )

    def mode(self) -> str:
        return self.mode_box.currentData() or "here"

    def _mode_changed(self, *_) -> None:
        mode = self.mode()
        self.mode_help.setText(toolchain.MODE_HELP[mode])
        self.b_run.setText(f"{toolchain.MODE_BUTTON[mode]}   F5")
        uses_input = mode in ("here", "check", "bench")
        self.stdin_label.setVisible(uses_input)
        self.stdin_box.setVisible(uses_input)
        self.stdin_label.setText("Input (empty: uses <name>.in if there is one)" if mode == "check"
                                 else "Input (sent to stdin)")
        self.expected_label.setVisible(mode == "check")
        self.expected_box.setVisible(mode == "check")
        self.runs_row.setVisible(mode == "bench")
        self.args.setEnabled(mode != "exe")
        self._update_preview()
        self.save_soon()

    def _command(self, mode: str = "here") -> Plan | None:
        """The build for `mode`: the normal one, the standalone one (dist/) or the debug one."""
        if not self.file:
            return None
        lang = self._lang()
        if lang not in self._compilers:
            self._compilers[lang] = toolchain.find_compiler(lang)
        compiler = self._compilers[lang] or toolchain.compiler_name(lang)
        sources = toolchain.collect_sources(self.file, self._checked("whole_folder"))
        opts = self.options()
        if mode in ("exe", "exe_run"):
            opts, out = toolchain.standalone_options(opts), toolchain.standalone_path(self.file)
        elif mode == "debug":
            opts, out = toolchain.debug_options(opts), toolchain.debug_path(self.file)
        else:
            out = toolchain.output_path(self.file)
        return Plan(toolchain.build_command(compiler, sources, out, opts), out, sources, opts, self.file)

    def _update_preview(self, *_):
        plan = self._command(self.mode()) if hasattr(self, "mode_box") else self._command()
        if not plan:
            self.preview.setText("Open a file to see the GCC command.")
            return
        shown = [Path(plan.cmd[0]).name] + [self._short(c) for c in plan.cmd[1:]]
        self.preview.setText(system.format_cmd(shown))

    def _short(self, arg: str) -> str:
        if self.file:
            try:
                return str(Path(arg).relative_to(self.file.parent))
            except ValueError:
                pass
        return arg

    # ------------------------------------------------------------- files
    def browse(self) -> None:
        start = str(self.file.parent) if self.file else ""
        chosen, _ = QFileDialog.getOpenFileName(self, "Choose a C or C++ file", start, FILE_FILTER)
        if chosen:
            self.set_file(Path(chosen))

    def browse_folder(self) -> None:
        start = str(self.explorer.folder or (self.file.parent if self.file else ""))
        chosen = QFileDialog.getExistingDirectory(self, "Choose a project folder", start)
        if chosen:
            self.open_folder(Path(chosen))

    def open_folder(self, folder: Path) -> None:
        """Show the folder in the explorer. Once it is scanned, if the current file is
        elsewhere, pick the folder's first file with a main(), so F5 works straight away."""
        self.explorer.open(folder, on_done=self._folder_ready)
        self.settings.set("folder", str(self.explorer.folder))
        self.save_soon()

    def _folder_ready(self) -> None:
        if not self.explorer.contains(self.file):
            first = self.explorer.scan.first_runnable() if self.explorer.scan else None
            if first:
                self.set_file(first)
        self.explorer.select(self.file)

    def set_file(self, path: Path) -> None:
        # Absolute, because GCC runs inside the file's folder: a relative path such as
        # "examples/c/a.c" would then point at examples/c/examples/c/a.c.
        path = Path(path).resolve()
        lang = toolchain.detect_language(path)
        if lang is None:
            self.console.write(f"warning: {path.name} is not a .c or .cpp file. Choose the language yourself.")
        elif lang != self._lang():
            self.lang.set_value(LANG_LABEL[lang])
            self._lang_changed(LANG_LABEL[lang])
        self.file = path
        self.file_label.setText(path.name)
        self.file_label.setProperty("role", None)
        self.file_label.style().unpolish(self.file_label)
        self.file_label.style().polish(self.file_label)
        self.file_dir.setText(str(path.parent))
        recent = [str(path)] + [r for r in self.settings.get("recent", []) if r != str(path)]
        self.settings.set("recent", recent[:8])
        self._fill_recent()
        self.explorer.select(path)
        self._update_preview()
        self.save_soon()                          # arrow keys in the tree: one write, not one per file

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        recent = self.settings.get("recent", [])
        for r in recent:
            p = Path(r)
            action = self.recent_menu.addAction(f"{p.name}   ·   {p.parent}")
            action.triggered.connect(lambda _=False, path=p: self._open_recent(path))
        self.recent_btn.setEnabled(bool(recent))

    def _open_recent(self, path: Path) -> None:
        if path.is_file():
            self.set_file(path)
        else:
            self.console.write(f"error: {path} no longer exists.")

    def edit_in_vscode(self) -> None:
        if self.file:
            self.open_in_vscode(self.file)

    def open_in_vscode(self, path: Path) -> None:
        if not system.open_in_vscode(path):
            self.console.write("warning: VS Code not found. Install the Classic pack.")

    # ------------------------------------------------------- build & run
    def _needs_build(self, plan: Plan) -> bool:
        rebuild, reason = toolchain.needs_build(plan.out, plan.cmd, self.gcc_version, plan.sources)
        if rebuild and plan.out.exists():
            self.tasks.log(f"Rebuilding: {reason}.")
        return rebuild

    def _record_build(self, plan: Plan) -> None:
        """Remember the command and the included headers, for the next rebuild check."""
        rc, text = system.run_capture(toolchain.dependency_command(plan.cmd[0], plan.sources, plan.opts),
                                      env=system.toolchain_env(), cwd=plan.cwd, timeout=60)
        deps = []
        if rc == 0:
            for dep in toolchain.parse_depfile(text):
                p = Path(dep)
                deps.append(str(p if p.is_absolute() else (plan.cwd / p).resolve()))
        toolchain.write_stamp(plan.out, plan.cmd, self.gcc_version, deps)

    def _compile(self, plan: Plan) -> bool:
        cmd, out = plan.cmd, plan.out
        if not Path(cmd[0]).is_absolute() and not system.find_tool(cmd[0]):
            self.tasks.log(f"error: {cmd[0]} not found. Install the Classic pack in the setup app.")
            self.tasks.ui(lambda: self._set_status("error", "GCC not found"))
            return False
        out.parent.mkdir(parents=True, exist_ok=True)
        self.tasks.ui(lambda: (self.b_stop.setEnabled(True), self._set_status("busy", "Compiling...")))
        start = time.perf_counter()
        rc = system.run_stream(cmd, self.tasks.log, env=system.toolchain_env(), cwd=plan.cwd)
        took = time.perf_counter() - start
        if rc == system.EXIT_CANCELLED:
            self.tasks.ui(lambda: self._set_status("error", "Build cancelled"))
            return False
        if rc == 0:
            self._record_build(plan)
            self.tasks.log(f"✓ Built {out.name} in {took:.2f} s")
            self.tasks.ui(lambda: self._set_status("ok", f"Built in {took:.2f} s"))
            return True
        self.tasks.log(f"error: build failed (exit {rc}).")
        self.tasks.ui(lambda: self._set_status("error", "Build failed"))
        return False

    def _build_if_needed(self, plan: Plan) -> bool:
        return not self._needs_build(plan) or self._compile(plan)

    def _ready(self, mode: str = "here") -> Plan | None:
        if self.tasks.busy:
            return None
        if not self.file:
            self.browse()
            if not self.file:
                return None
        if not self.file.is_file():
            self.console.write(f"error: {self.file} no longer exists.")
            return None
        self._save()
        self.console.clear()
        self.b_show.hide()
        return self._command(mode)

    def build(self) -> None:
        plan = self._ready()
        if plan:
            self.tasks.run("Building...", lambda: self._compile(plan))

    def run(self, mode: str | None = None) -> None:
        """F5: build if needed, then do what the run mode says."""
        mode = mode or self.mode()
        plan = self._ready(mode)
        if not plan:
            return
        args = toolchain.split_flags(self.args.text())
        stdin_text = self.stdin_box.toPlainText()
        expected = self.expected_box.toPlainText()
        runs = self.runs_box.value()
        jobs = {
            "here": lambda: self._run_captured(plan.out, args, stdin_text, plan.cwd),
            "terminal": lambda: self._run_external(plan.out, args, plan.cwd),
            "exe": lambda: self._report_standalone(plan),
            "exe_run": lambda: (self._report_standalone(plan),
                                self._run_external(plan.out, args, plan.cwd, standalone=True)),
            "check": lambda: self._run_check(plan, args, stdin_text, expected),
            "bench": lambda: self._run_bench(plan, args, stdin_text, runs),
            "debug": lambda: self._run_debugger(plan, args),
        }

        def job():
            if mode == "bench" and plan.opts.optimisation == "-O0":
                self.tasks.log("note: built with -O0, so times are slower than they could be. "
                               "Choose -O2 to measure real speed.")
            if self._build_if_needed(plan):
                jobs[mode]()
        self.tasks.run(f"{toolchain.MODE_TEXT[mode]}...", job)

    # ---------------------------------------------------------- run modes
    def _popen(self, exe: Path, args: list[str], cwd: Path, **kw) -> subprocess.Popen:
        return subprocess.Popen([str(exe), *args], cwd=cwd, env=system.toolchain_env(), **kw,
                                **({"creationflags": system.CREATE_NO_WINDOW} if system.IS_WINDOWS
                                   else {"start_new_session": True}))

    def _run_external(self, exe: Path, args: list[str], cwd: Path, standalone: bool = False) -> None:
        # A standalone executable starts with the user's own environment, without GCC's
        # folders on PATH: if it still runs, it really does not need them.
        env = dict(os.environ) if standalone else system.toolchain_env()
        try:
            if system.IS_WINDOWS:
                # A batch file, not a "cmd /c ..." string: arguments with & or % stay literal.
                script = cwd / "build" / (exe.stem + "-run.cmd")
                script.parent.mkdir(parents=True, exist_ok=True)
                script.write_text(toolchain.windows_run_script(exe, args), encoding="utf-8", newline="")
                subprocess.Popen(["cmd.exe", "/c", str(script)], cwd=cwd, env=env,
                                 creationflags=system.CREATE_NEW_CONSOLE)
            else:
                system.open_terminal(system.format_cmd([str(exe), *args]) + '; echo; echo "[exit code $?]"', cwd)
        except (OSError, RuntimeError) as exc:
            self.tasks.log(f"error: could not open a terminal: {exc}")
            self.tasks.ui(lambda: self._set_status("error", "No terminal found"))
            return
        self.tasks.log(f"Started {exe.name} in a separate terminal.")
        self.tasks.ui(lambda: self._set_status("ok", "Running in a separate terminal"))

    def _run_captured(self, exe: Path, args: list[str], stdin_text: str, cwd: Path,
                      collect: bool = False) -> tuple[int | None, str]:
        """Run in the Output panel. With collect=True also return what it printed."""
        self.tasks.log("$ " + system.format_cmd([exe.name, *args]))
        self.tasks.log("──────────────────────────────")
        try:
            proc = self._popen(exe, args, cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
        except OSError as exc:
            self.tasks.log(f"error: could not start the program: {exc}")
            self.tasks.ui(lambda: self._set_status("error", "Could not start the program"))
            return None, ""
        self.proc = proc
        self.tasks.ui(lambda: (self.b_stop.setEnabled(True), self._set_status("busy", "Running...")))

        def feed():
            try:
                if stdin_text:
                    proc.stdin.write(stdin_text.encode("utf-8") + (b"" if stdin_text.endswith("\n") else b"\n"))
                proc.stdin.close()
            except OSError:
                pass
        threading.Thread(target=feed, daemon=True).start()

        start = time.perf_counter()
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        kept: list[str] = []
        kept_size = 0
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            text = decoder.decode(chunk).replace("\r\n", "\n")
            self.tasks.raw(text)
            if collect and kept_size < 50_000_000:
                kept.append(text)
                kept_size += len(text)
        tail = decoder.decode(b"", final=True)
        if tail:
            self.tasks.raw(tail)
            kept.append(tail)
        rc = proc.wait()
        proc.stdout.close()
        took = time.perf_counter() - start
        self.proc = None
        self.tasks.raw("\n")
        self.tasks.log("──────────────────────────────")
        desc = toolchain.describe_exit(rc)
        self.tasks.log(f"✓ Finished in {took:.3f} s, {desc}" if rc == 0 else f"error: {desc} (after {took:.3f} s)")
        state = "ok" if rc == 0 else "error"
        self.tasks.ui(lambda: (self.b_stop.setEnabled(False), self._set_status(state, f"Finished: {desc}")))
        return rc, "".join(kept)

    def _report_standalone(self, plan: Plan) -> None:
        size = plan.out.stat().st_size / 1024 if plan.out.exists() else 0
        self.tasks.log(f"✓ Standalone executable: {plan.out}  ({size:,.0f} KB)")
        if system.IS_MAC:
            self.tasks.log("note: macOS does not allow fully static programs; the GCC runtime is linked in, "
                           "the system libraries come from macOS itself.")
        else:
            self.tasks.log("It is statically linked: copy it to another computer with the same system "
                           "and it runs without GCC.")
        if system.IS_WINDOWS:
            self.tasks.log("note: Windows SmartScreen may warn about it on other PCs, because it is not signed.")
        out = plan.out

        def done():
            self.last_output = out
            self.b_show.show()
            self._set_status("ok", f"Made {out.name}")
        self.tasks.ui(done)

    def _run_check(self, plan: Plan, args: list[str], stdin_text: str, expected: str) -> None:
        sample_in, sample_out = toolchain.sample_files(plan.file)
        if not stdin_text and sample_in:
            stdin_text = sample_in.read_text(encoding="utf-8", errors="replace")
            self.tasks.log(f"Input from {sample_in.name}")
        if not expected:
            if not sample_out:
                self.tasks.log(f"error: nothing to compare with. Fill the Expected output box, or put "
                               f"{plan.file.stem}.out next to {plan.file.name}.")
                self.tasks.ui(lambda: self._set_status("error", "No expected output"))
                return
            expected = sample_out.read_text(encoding="utf-8", errors="replace")
            self.tasks.log(f"Expected output from {sample_out.name}")
        rc, got = self._run_captured(plan.out, args, stdin_text, plan.cwd, collect=True)
        if rc is None:
            return
        same, why = toolchain.compare_output(got, expected)
        if same and rc == 0:
            self.tasks.log(f"✓ Accepted: {why}")
            self.tasks.ui(lambda: self._set_status("ok", "Accepted: output matches"))
        elif same:
            self.tasks.log(f"error: right output, but the program ended with {toolchain.describe_exit(rc)}")
            self.tasks.ui(lambda: self._set_status("error", "Runtime error"))
        else:
            self.tasks.log(f"error: wrong answer, {why}")
            self.tasks.ui(lambda: self._set_status("error", "Wrong answer"))

    def _run_bench(self, plan: Plan, args: list[str], stdin_text: str, runs: int) -> None:
        data = (stdin_text + ("" if not stdin_text or stdin_text.endswith("\n") else "\n")).encode("utf-8")
        self.tasks.log(f"$ {system.format_cmd([plan.out.name, *args])}   × {runs}, output hidden")
        self.tasks.ui(lambda: (self.b_stop.setEnabled(True), self._set_status("busy", "Benchmarking...")))
        times: list[float] = []
        for i in range(1, runs + 1):
            if system.cancelled():
                break
            try:
                proc = self._popen(plan.out, args, plan.cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                self.tasks.log(f"error: could not start the program: {exc}")
                return
            self.proc = proc
            start = time.perf_counter()
            try:
                proc.communicate(data)
            except OSError:
                proc.wait()
            took = time.perf_counter() - start
            self.proc = None
            if proc.returncode != 0:
                if system.cancelled():                # stopped by you
                    break
                self.tasks.log(f"error: run {i} failed, {toolchain.describe_exit(proc.returncode)}")
                self.tasks.ui(lambda: self._set_status("error", "A run failed"))
                return
            times.append(took)
            self.tasks.log(f"  run {i:>3}: {took * 1000:9.2f} ms")
        if not times:
            self.tasks.ui(lambda: self._set_status("error", "Benchmark stopped"))
            return
        summary = toolchain.timing_summary(times)
        self.tasks.log(f"✓ {len(times)} runs: {summary}")
        self.tasks.ui(lambda: self._set_status("ok", summary))

    def _run_debugger(self, plan: Plan, args: list[str]) -> None:
        debugger = toolchain.find_debugger()
        if not debugger:
            self.tasks.log("error: no debugger found. Install GDB from the Classic pack in the setup app"
                           + (" (or the Xcode tools for LLDB)." if system.IS_MAC else "."))
            self.tasks.ui(lambda: self._set_status("error", "No debugger found"))
            return
        cmd = toolchain.debugger_command(debugger, plan.out, args)
        try:
            if system.IS_WINDOWS:
                script = plan.out.parent / (plan.out.stem + "-gdb.cmd")
                script.write_text(toolchain.windows_script(cmd), encoding="utf-8", newline="")
                subprocess.Popen(["cmd.exe", "/c", str(script)], cwd=plan.cwd, env=system.toolchain_env(),
                                 creationflags=system.CREATE_NEW_CONSOLE)
            else:
                system.open_terminal(system.format_cmd(cmd), plan.cwd)
        except (OSError, RuntimeError) as exc:
            self.tasks.log(f"error: could not open a terminal: {exc}")
            return
        self.tasks.log(f"Started {Path(debugger).name} on {plan.out.name} in a terminal. "
                       "Try: break main, run, next, print <variable>, continue, quit.")
        self.tasks.ui(lambda: self._set_status("ok", "Debugger open in a terminal"))

    def show_output(self) -> None:
        if self.last_output:
            system.open_folder(self.last_output.parent)

    def stop(self) -> None:
        """Stop the running program, and a build in progress, with any child processes."""
        stopped = False
        proc = self.proc
        if proc and proc.poll() is None:
            system.kill_tree(proc)
            stopped = True
        if self.tasks.busy:
            self.tasks.cancel()
            stopped = True
        if stopped:
            self.tasks.log("Stopped by you.")

    # ------------------------------------------------------------ shared
    def _set_status(self, state: str, text: str) -> None:
        self._status_state = state
        self.status_dot.set(state)
        self.status_label.setText(text)

    def _on_busy(self, busy: bool, text: str) -> None:
        self.b_build.setEnabled(not busy)
        self.b_run.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self._set_status("busy", text)
        else:
            self.b_stop.setEnabled(False)
            if getattr(self, "_status_state", "") == "busy":   # the job set no result of its own
                self._set_status("missing", "Ready")

    def save_soon(self) -> None:
        self._save_timer.start()

    def _save(self) -> None:
        self._save_timer.stop()
        s = self.settings
        s.set("file", str(self.file) if self.file else None)
        s.set("folder", str(self.explorer.folder) if self.explorer.folder else None)
        s.set("language", self._lang())
        s.set("standards", self.std_by_lang)
        s.set("optimisation", self.opt.value())
        for key, box in self.checks.items():
            s.set(key, box.isChecked())
        s.set("extra_flags", self.extra.text())
        s.set("args", self.args.text())
        s.set("run_mode", self.mode())
        s.set("bench_runs", self.runs_box.value())
        s.save()

    def changeEvent(self, event) -> None:
        # Back from VS Code: a main() may have been added or removed, rescan (only changed files are read).
        # Not more than once a second: closing a menu or a dialog also activates the window.
        if (event.type() == QEvent.Type.ActivationChange and self.isActiveWindow()
                and time.monotonic() - self.explorer.last_scan > 1.0):
            self.explorer.refresh()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        self.stop()
        self._save()
        super().closeEvent(event)


def main() -> int:
    app = ui.create_app("C/C++ DevKit Launcher")
    window = LauncherWindow()
    if len(sys.argv) > 1:                         # launcher_app.py <file or folder>
        target = Path(sys.argv[1]).expanduser()
        if target.is_dir():
            window.open_folder(target)
        elif target.is_file():
            window.set_file(target)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
