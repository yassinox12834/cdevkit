"""C/C++ DevKit Launcher: pick a .c or .cpp file, choose the standard, build and run with GCC.

Run with launcher.bat (Windows), launcher.command (macOS), ./launcher.sh (Linux), or:  python launcher_app.py
Shortcuts: Ctrl+O open, Ctrl+B build, F5 run (rebuilds if needed), Shift+F5 stop.
"""

from __future__ import annotations

import codecs
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QMainWindow, QMenu, QPlainTextEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from devkit import system, toolchain
from devkit import qt as ui

FILE_FILTER = "C and C++ sources (*.c *.cpp *.cc *.cxx *.c++);;C sources (*.c);;C++ sources (*.cpp *.cc *.cxx *.c++);;All files (*)"
LANG_LABEL = {"c": "C", "cpp": "C++"}
LABEL_LANG = {v: k for k, v in LANG_LABEL.items()}


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("C/C++ DevKit Launcher")
        self.resize(1180, 780)
        self.setMinimumSize(960, 600)
        self.settings = system.Settings("launcher")
        self.proc: subprocess.Popen | None = None
        self.file: Path | None = None
        self.gcc_major = 0
        s = self.settings
        self.std_by_lang: dict[str, str] = dict(toolchain.DEFAULT_STANDARD, **s.get("standards", {}))

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)
        outer.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_panel())
        body.addWidget(self._build_output(), 1)
        outer.addLayout(body, 1)

        self.tasks = ui.TaskRunner(self.console)
        self.tasks.busy_changed.connect(self._on_busy)

        for key, slot in (("Ctrl+O", self.browse), ("Ctrl+B", self.build), ("F5", self.run),
                          ("Shift+F5", self.stop)):
            QShortcut(QKeySequence(key), self, slot)

        # Any option change updates the command preview.
        for box in self.checks.values():
            box.toggled.connect(self._update_preview)
        self.lang.changed.connect(self._lang_changed)
        self.std.currentTextChanged.connect(self._std_changed)
        self.opt.changed.connect(lambda _: self._update_preview())
        self.extra.textChanged.connect(self._update_preview)

        last = s.get("file")
        if last and Path(last).is_file():
            self.set_file(Path(last))
        else:
            self._update_preview()
        self.console.write("Open a .c or .cpp file (Ctrl+O), then press F5 to build and run.", "muted")
        self.tasks.run("Looking for GCC...", lambda: toolchain.compiler_info("cpp"), self._show_compiler)

    # ------------------------------------------------------------ layout
    def _build_header(self) -> QWidget:
        self.compiler_pill = ui.label("GCC: checking...", "pill")
        self.b_build = ui.button("Build   Ctrl+B", self.build)
        self.b_run = ui.button("Run   F5", self.run, primary=True)
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
        lay.addWidget(ui.row(ui.button("Open file...", self.browse), self.recent_btn,
                             ui.button("Edit", self.edit_in_vscode)))
        self._fill_recent()

        self._caps(lay, "Language and standard")
        lang = s.get("language", "cpp")
        self.lang = ui.Segmented(["C", "C++"], LANG_LABEL[lang])
        self.std = QComboBox()
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
        lay.addWidget(ui.label("Arguments", "muted"))
        self.args = QLineEdit(s.get("args", ""))
        self.args.setPlaceholderText("arg1 arg2")
        lay.addWidget(self.args)
        check("external", "Run in a separate terminal", False,
              "Use it for programs that ask for input (scanf, std::cin).")
        lay.addWidget(ui.label("Input (sent to stdin)", "muted"))
        self.stdin_box = QPlainTextEdit()
        self.stdin_box.setFont(ui.mono_font())
        self.stdin_box.setFixedHeight(70)
        self.stdin_box.setPlaceholderText("4 8 15 16 23 42")
        lay.addWidget(self.stdin_box)
        lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        lay.addWidget(ui.row(self.status_dot, self.status_label, spacing=6))
        return w

    # ------------------------------------------------------------ state
    def _show_compiler(self, info) -> None:
        if not isinstance(info, toolchain.CompilerInfo) or not info.path:
            self._pill("GCC not found: install the Classic pack", ui.ERR)
        elif info.is_clang:
            self._pill("Only Apple Clang found: install GCC from the Classic pack", ui.WARN)
        else:
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

    def _command(self):
        if not self.file:
            return None
        lang = self._lang()
        compiler = toolchain.find_compiler(lang) or toolchain.compiler_name(lang)
        sources = toolchain.collect_sources(self.file, self._checked("whole_folder"))
        out = toolchain.output_path(self.file)
        return toolchain.build_command(compiler, sources, out, self.options()), out, sources

    def _update_preview(self, *_):
        built = self._command()
        if not built:
            self.preview.setText("Open a file to see the GCC command.")
            return
        cmd, _, _ = built
        shown = [Path(cmd[0]).name] + [self._short(c) for c in cmd[1:]]
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

    def set_file(self, path: Path) -> None:
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
        self._update_preview()
        self._save()

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
        if self.file and not system.open_in_vscode(self.file):
            self.console.write("warning: VS Code not found. Install the Classic pack.")

    # ------------------------------------------------------- build & run
    def _needs_build(self, out: Path, sources: list[Path]) -> bool:
        if not out.exists():
            return True
        built_at = out.stat().st_mtime
        headers = [p for p in self.file.parent.glob("*.h*") if p.is_file()]
        return any(p.stat().st_mtime > built_at for p in [*sources, *headers] if p.exists())

    def _compile(self, cmd: list[str], out: Path) -> bool:
        if not Path(cmd[0]).is_absolute() and not system.find_tool(cmd[0]):
            self.tasks.log(f"error: {cmd[0]} not found. Install the Classic pack in the setup app.")
            return False
        out.parent.mkdir(parents=True, exist_ok=True)
        self.tasks.ui(lambda: self._set_status("busy", "Compiling..."))
        start = time.perf_counter()
        rc = system.run_stream(cmd, self.tasks.log, env=system.toolchain_env(), cwd=self.file.parent)
        took = time.perf_counter() - start
        if rc == 0:
            self.tasks.log(f"✓ Built {out.name} in {took:.2f} s")
            self.tasks.ui(lambda: self._set_status("ok", f"Built in {took:.2f} s"))
            return True
        self.tasks.log(f"error: build failed (exit {rc}).")
        self.tasks.ui(lambda: self._set_status("error", "Build failed"))
        return False

    def _ready(self):
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
        return self._command()

    def build(self) -> None:
        built = self._ready()
        if built:
            cmd, out, _ = built
            self.tasks.run("Building...", lambda: self._compile(cmd, out))

    def run(self) -> None:
        built = self._ready()
        if not built:
            return
        cmd, out, sources = built
        args = toolchain.split_flags(self.args.text())
        stdin_text = self.stdin_box.toPlainText()
        external = self._checked("external")

        def job():
            if self._needs_build(out, sources) and not self._compile(cmd, out):
                return
            if external:
                self._run_external(out, args)
            else:
                self._run_captured(out, args, stdin_text)
        self.tasks.run("Running...", job)

    def _run_external(self, exe: Path, args: list[str]) -> None:
        cwd = self.file.parent
        if system.IS_WINDOWS:
            line = " ".join(subprocess.list2cmdline([a]) for a in [str(exe), *args])
            # cmd /c strips the outer quotes; call + %^errorlevel% reads the exit code after the run.
            command = f'cmd.exe /c "{line} & echo. & call echo [exit code %^errorlevel%] & pause"'
            subprocess.Popen(command, cwd=cwd, env=system.toolchain_env(), creationflags=system.CREATE_NEW_CONSOLE)
        else:
            system.open_terminal(system.format_cmd([str(exe), *args]) + '; echo; echo "[exit code $?]"', cwd)
        self.tasks.log(f"Started {exe.name} in a separate terminal.")
        self.tasks.ui(lambda: self._set_status("ok", "Running in a separate terminal"))

    def _run_captured(self, exe: Path, args: list[str], stdin_text: str) -> None:
        self.tasks.log("$ " + system.format_cmd([exe.name, *args]))
        self.tasks.log("──────────────────────────────")
        try:
            proc = subprocess.Popen([str(exe), *args], cwd=self.file.parent, env=system.toolchain_env(),
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    **({"creationflags": system.CREATE_NO_WINDOW} if system.IS_WINDOWS else {}))
        except OSError as exc:
            self.tasks.log(f"error: could not start the program: {exc}")
            return
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
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            self.tasks.raw(decoder.decode(chunk).replace("\r\n", "\n"))
        tail = decoder.decode(b"", final=True)
        if tail:
            self.tasks.raw(tail)
        rc = proc.wait()
        took = time.perf_counter() - start
        self.proc = None
        self.tasks.raw("\n")
        self.tasks.log("──────────────────────────────")
        desc = toolchain.describe_exit(rc)
        self.tasks.log(f"✓ Finished in {took:.3f} s, {desc}" if rc == 0 else f"error: {desc} (after {took:.3f} s)")
        state = "ok" if rc == 0 else "error"
        self.tasks.ui(lambda: (self.b_stop.setEnabled(False), self._set_status(state, f"Finished: {desc}")))

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.console.write("Stopped by you.", "warn")

    # ------------------------------------------------------------ shared
    def _set_status(self, state: str, text: str) -> None:
        self.status_dot.set(state)
        self.status_label.setText(text)

    def _on_busy(self, busy: bool, _text: str) -> None:
        self.b_build.setEnabled(not busy)
        self.b_run.setEnabled(not busy)
        if not busy:
            self.b_stop.setEnabled(False)

    def _save(self) -> None:
        s = self.settings
        s.set("file", str(self.file) if self.file else None)
        s.set("language", self._lang())
        s.set("standards", self.std_by_lang)
        s.set("optimisation", self.opt.value())
        for key, box in self.checks.items():
            s.set(key, box.isChecked())
        s.set("extra_flags", self.extra.text())
        s.set("args", self.args.text())
        s.save()

    def closeEvent(self, event) -> None:
        self.stop()
        self._save()
        super().closeEvent(event)


def main() -> int:
    app = ui.create_app("C/C++ DevKit Launcher")
    window = LauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
