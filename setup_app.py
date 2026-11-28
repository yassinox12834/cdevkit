"""C/C++ DevKit Setup: install packs, configure them, verify the toolchain.

Run with setup.bat (Windows), setup.command (macOS), ./setup.sh (Linux), or:  python setup_app.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from devkit import __version__, configure, system, toolchain
from devkit import qt as ui
from devkit.installer import Installer
from devkit.packs import ALL_COMPONENTS, PACKS, Component, Pack
from devkit.project_template import create_project
from devkit.vscode_settings import apply_toolchain_settings

HERE = Path(__file__).resolve().parent

METHOD_LABEL = {"winget": "winget", "msys": "MSYS2", "brew": "Homebrew", "cask": "Homebrew",
                "special": "macOS", "script": "repository", "vscode": "VS Code"}

# (label, executable, args). "{gcc}" and "{g++}" are resolved by toolchain.find_compiler.
VERIFY_TOOLS = [
    ("gcc", "{gcc}", ["--version"]),
    ("g++", "{g++}", ["--version"]),
    ("lldb" if system.IS_MAC else "gdb", "lldb" if system.IS_MAC else "gdb", ["--version"]),
    ("cmake", "cmake", ["--version"]),
    ("ninja", "ninja", ["--version"]),
    ("make", "mingw32-make" if system.IS_WINDOWS else "make", ["--version"]),
    ("git", "git", ["--version"]),
    ("VS Code", "code", ["--version"]),
    ("clang-format", "clang-format", ["--version"]),
    ("clang-tidy", "clang-tidy", ["--version"]),
    ("clangd", "clangd", ["--version"]),
    ("cppcheck", "cppcheck", ["--version"]),
    ("GitHub CLI", "gh", ["--version"]),
    ("ccache", "ccache", ["--version"]),
    ("doxygen", "doxygen", ["--version"]),
]


class SetupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("C/C++ DevKit Setup")
        self.resize(1180, 800)
        self.setMinimumSize(980, 640)

        self.status: dict[str, bool] = {}
        self.rows: dict[str, tuple[ui.Dot, QPushButton]] = {}
        self.pack_buttons: dict[str, QPushButton] = {}
        self.actions: list[QPushButton] = []

        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        main = QWidget()
        main_lay = QVBoxLayout(main)
        main_lay.setContentsMargins(22, 18, 22, 18)
        main_lay.setSpacing(10)
        outer.addWidget(main, 1)

        self.stack = QStackedWidget()
        log_frame, self.console = ui.console_panel("Log")
        self.tasks = ui.TaskRunner(self.console)
        self.tasks.busy_changed.connect(self._on_busy)
        self.installer = Installer(self.tasks.log)
        self.manager = self.installer.manager

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(10)
        splitter.addWidget(self.stack)
        bottom = QWidget()
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(0, 0, 0, 0)
        bottom_lay.setSpacing(6)
        self.status_label = ui.label("Ready", "muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)              # moving bar while busy
        self.progress.hide()
        self.b_cancel = ui.button("Cancel", self.cancel)
        self.b_cancel.setToolTip("Stop the command that is running now. Stopping an install halfway can leave "
                                 "that one package incomplete: install it again afterwards.")
        self.b_cancel.hide()
        bottom_lay.addWidget(ui.row(self.status_label, self.progress, self.b_cancel, stretch_end=False))
        bottom_lay.addWidget(log_frame, 1)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 200])
        main_lay.addWidget(splitter, 1)

        self.pages = {
            "packs": self._build_packs_page(),
            "configure": self._build_configure_page(),
            "verify": self._build_verify_page(),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.show_page("packs")

        if system.IS_LINUX and not self.manager:
            self.console.write("warning: no apt, dnf or pacman found. Only VS Code extensions can be installed.")
        where = f"{system.PLATFORM_NAME} ({self.manager})" if self.manager else system.PLATFORM_NAME
        self.console.write(f"Detected {where}. Start with the Classic pack: GCC, CMake, Git and VS Code.", "muted")
        self.refresh_status()

    # ------------------------------------------------------------ layout
    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 22, 14, 16)
        lay.setSpacing(2)
        title = ui.label("C/C++ DevKit", "heading")
        lay.addWidget(title)
        lay.addWidget(ui.label(f"GCC toolchain for {system.PLATFORM_NAME}", "muted"))
        lay.addSpacing(22)

        self.nav: dict[str, QPushButton] = {}
        group = QButtonGroup(side)
        for key, text in (("packs", "Packs"), ("configure", "Configure"), ("verify", "Verify")):
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            group.addButton(b)
            lay.addWidget(b)
            self.nav[key] = b

        lay.addStretch(1)
        lay.addWidget(ui.button("Open code launcher", self.open_launcher, primary=True))
        lay.addSpacing(8)
        lay.addWidget(ui.label(f"v{__version__}", "faint"))
        return side

    def show_page(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)

    def _page(self, title: str, subtitle: str, *header_widgets) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        head_text = QWidget()
        head_lay = QVBoxLayout(head_text)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(2)
        head_lay.addWidget(ui.label(title, "title"))
        head_lay.addWidget(ui.label(subtitle, "muted"))
        lay.addWidget(ui.row(head_text, "stretch", *header_widgets, stretch_end=False))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().setSingleStep(24)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 8, 0)
        body_lay.setSpacing(12)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        return page, body_lay

    def _action(self, text: str, on_click, primary: bool = False) -> QPushButton:
        b = ui.button(text, on_click, primary=primary)
        self.actions.append(b)
        return b

    # ------------------------------------------------------------- packs
    def _build_packs_page(self) -> QWidget:
        page, body = self._page("Packs", "Pick what to install. Already installed items are skipped.",
                                self._action("Refresh status", self.refresh_status))
        for pack in PACKS:
            comps = pack.available(system.PLATFORM, self.manager)
            if not comps:
                continue
            frame, lay = ui.card()
            title_row = [ui.label(pack.title, "heading")]
            if pack.recommended:
                title_row.append(ui.label("RECOMMENDED", "badge"))
            pb = self._action("Install pack", lambda p=pack: self.install_pack(p), primary=pack.recommended)
            self.pack_buttons[pack.key] = pb
            text = QWidget()
            text.setObjectName("row")
            text_lay = QVBoxLayout(text)
            text_lay.setContentsMargins(0, 0, 0, 0)
            text_lay.setSpacing(2)
            text_lay.addWidget(ui.row(*title_row))
            text_lay.addWidget(ui.label(pack.subtitle, "muted"))
            lay.addWidget(ui.row(text, "stretch", pb, stretch_end=False))
            for comp in comps:
                lay.addWidget(ui.divider())
                lay.addWidget(self._component_row(comp))
            body.addWidget(frame)
        body.addStretch(1)
        return page

    def _component_row(self, comp: Component) -> QWidget:
        method = comp.source(system.PLATFORM, self.manager)[0]
        text = QWidget()
        text.setObjectName("row")
        t = QVBoxLayout(text)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(1)
        t.addWidget(ui.row(ui.label(comp.name), ui.label(METHOD_LABEL.get(method, self.manager or ""), "faint")))
        t.addWidget(ui.label(comp.summary, "muted"))
        dot = ui.Dot()
        b = self._action("Install", lambda c=comp: self.install_one(c))
        b.setFixedWidth(96)
        self.rows[comp.key] = (dot, b)
        return ui.row(ui.tile(comp.mono, comp.category), text, "stretch", dot, b, spacing=12, stretch_end=False)

    def refresh_status(self) -> None:
        comps = [c for p in PACKS for c in p.available(system.PLATFORM, self.manager)]
        for dot, _ in self.rows.values():
            dot.set("busy")
        self.tasks.run("Checking what is installed...", lambda: self.installer.statuses(comps), self._apply_status)

    def _apply_status(self, result) -> None:
        if not isinstance(result, dict):
            return
        self.status = result
        for key, (dot, b) in self.rows.items():
            ok = result.get(key, False)
            dot.set("ok" if ok else "missing")
            b.setText("Installed" if ok else "Install")
        for pack in PACKS:
            if pack.key not in self.pack_buttons:
                continue
            comps = pack.available(system.PLATFORM, self.manager)
            missing = sum(not result.get(c.key) for c in comps)
            self.pack_buttons[pack.key].setText("Installed" if missing == 0 else f"Install pack ({missing})")
        self._update_action_states()

    def install_one(self, comp: Component) -> None:
        def job():
            ok = self.installer.install(comp)
            if ok:                                   # nothing to configure after a failed install
                self.installer.post_configure([comp])
            return ok
        self.rows[comp.key][0].set("busy")
        self.tasks.run(f"Installing {comp.name}...", job, lambda _: self.refresh_status())

    def install_pack(self, pack: Pack) -> None:
        def job():
            done, failed = self.installer.install_pack(pack)
            self.tasks.log(f"── {pack.title}: {done} ok, {failed} not done ──")
            if failed == 0:
                self.tasks.log("✓ Done. Open a NEW terminal or restart VS Code so they see the new PATH.")
        self.tasks.run(f"Installing {pack.title}...", job, lambda _: self.refresh_status())

    # --------------------------------------------------------- configure
    def _section(self, body: QVBoxLayout, title: str, text: str) -> QVBoxLayout:
        frame, lay = ui.card()
        lay.addWidget(ui.label(title, "heading"))
        lay.addWidget(ui.label(text, "muted", wrap=True))
        lay.addSpacing(4)
        body.addWidget(frame)
        return lay

    def _build_configure_page(self) -> QWidget:
        page, body = self._page("Configure", "Settings applied after installing. Each button is safe to click twice.")

        path_text = {
            "windows": "Puts GCC's folder on your PATH so every terminal and VS Code can find it, "
                       "and points VS Code's C/C++ extension at GCC.",
            "macos": "Adds Homebrew to your shell profile so Terminal and VS Code find GCC, "
                     "and points VS Code's C/C++ extension at Homebrew's GCC instead of Apple Clang.",
            "linux": "Linux packages already land on PATH, so this only points VS Code's C/C++ extension at GCC.",
        }[system.PLATFORM]
        t = self._section(body, "Toolchain", path_text)
        self.path_dot = ui.Dot()
        self.path_label = ui.label("", "muted")
        widgets = [self.path_dot, self.path_label, "stretch"]
        if not system.IS_LINUX:
            widgets.append(self._action("Add to PATH", self.add_path))
        widgets.append(self._action("Configure VS Code for GCC", self.configure_vscode))
        t.addWidget(ui.row(*widgets, stretch_end=False))
        self._update_path_label()

        g = self._section(body, "Git identity", "Every commit is signed with this name and email. Use your GitHub email.")
        self.git_name = QLineEdit()
        self.git_name.setPlaceholderText("Your name")
        self.git_email = QLineEdit()
        self.git_email.setPlaceholderText("you@example.com")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.addWidget(self.git_name, 0, 0)
        grid.addWidget(self.git_email, 0, 1)
        grid.addWidget(self._action("Save identity", self.save_git_identity, primary=True), 0, 2)
        g.addLayout(grid)
        g.addWidget(ui.row(self._action("Apply recommended Git settings", self.git_defaults)))
        self.tasks.run("Reading Git config...",
                       lambda: (configure.git_get("user.name"), configure.git_get("user.email")),
                       self._fill_git)

        h = self._section(body, "GitHub", "Sign in once with the GitHub CLI; Git then pushes without asking for "
                                          "a password. Needs GitHub CLI from the Extras pack.")
        h.addWidget(ui.row(
            self._action("Sign in to GitHub", lambda: configure.github_login(self.tasks.log), primary=True),
            self._action("Check sign-in", lambda: self.tasks.run(
                "Checking GitHub...", lambda: configure.github_status(self.tasks.log))),
            self._action("New repository on github.com", configure.open_new_repo_page),
            self._action("Install GitHub CLI", lambda: self.install_one(ALL_COMPONENTS["gh"])),
        ))

        p = self._section(body, "New project", "Creates a CMake project with VS Code build (Ctrl+Shift+B) and "
                                               "debug (F5) already set up, plus .clang-format, .gitignore and git init.")
        self.proj_dir = QLineEdit()
        self.proj_dir.setPlaceholderText("Choose a parent folder")
        self.proj_name = QLineEdit()
        self.proj_name.setPlaceholderText("my_project")
        self.proj_lang = ui.Segmented(["C", "C++"], "C++")
        self.proj_std = ui.ComboBox()
        self.proj_std.addItems(toolchain.CPP_STANDARDS)
        self.proj_std.setCurrentText(toolchain.DEFAULT_STANDARD["cpp"])
        self.proj_lang.changed.connect(self._proj_lang_changed)
        self.proj_open = QCheckBox("Open in VS Code")
        self.proj_open.setChecked(True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.addWidget(ui.label("Location", "muted"), 0, 0)
        grid.addWidget(self.proj_dir, 0, 1)
        grid.addWidget(ui.button("Browse", self.pick_project_dir), 0, 2)
        grid.addWidget(ui.label("Name", "muted"), 1, 0)
        grid.addWidget(self.proj_name, 1, 1)
        grid.addWidget(ui.row(self.proj_lang, self.proj_std, self.proj_open, spacing=12), 2, 1)
        grid.addWidget(ui.row(self._action("Create project", self.create_project, primary=True)), 3, 1)
        grid.setColumnStretch(1, 1)
        p.addLayout(grid)
        body.addStretch(1)
        return page

    def _fill_git(self, result) -> None:
        if isinstance(result, tuple):
            name, email = result
            if name and not self.git_name.text():
                self.git_name.setText(name)
            if email and not self.git_email.text():
                self.git_email.setText(email)

    def _update_path_label(self) -> None:
        state, text = system.path_status()
        self.path_dot.set(state)
        self.path_label.setText(text)

    def add_path(self) -> None:
        self.tasks.run("Updating PATH...", lambda: system.configure_path(self.tasks.log),
                       lambda _: self._update_path_label())

    def configure_vscode(self) -> None:
        def job():
            self.installer.invalidate()
            apply_toolchain_settings(self.tasks.log,
                                     use_clangd=self.installer.is_installed(ALL_COMPONENTS["ext-clangd"]))
        self.tasks.run("Configuring VS Code...", job)

    def save_git_identity(self) -> None:
        name, email = self.git_name.text(), self.git_email.text()
        self.tasks.run("Saving Git identity...", lambda: configure.set_git_identity(name, email, self.tasks.log))

    def git_defaults(self) -> None:
        self.tasks.run("Applying Git settings...", lambda: configure.apply_git_defaults(self.tasks.log))

    def _proj_lang_changed(self, value: str) -> None:
        lang = "c" if value == "C" else "cpp"
        self.proj_std.clear()
        self.proj_std.addItems(toolchain.STANDARDS[lang])
        self.proj_std.setCurrentText(toolchain.DEFAULT_STANDARD[lang])

    def pick_project_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Where should the project folder go?")
        if folder:
            self.proj_dir.setText(folder)

    def create_project(self) -> None:
        parent = self.proj_dir.text().strip()
        name = self.proj_name.text().strip() or "my_project"
        if not parent or not Path(parent).is_dir():
            self.console.write("error: choose an existing parent folder first.")
            return
        lang = "c" if self.proj_lang.value() == "C" else "cpp"
        std, open_it = self.proj_std.currentText(), self.proj_open.isChecked()

        def job():
            dest = create_project(Path(parent), name, lang, std, self.tasks.log)
            if dest and open_it and not system.open_in_vscode(dest):
                self.tasks.log("VS Code not found, so the project was not opened.")
        self.tasks.run("Creating project...", job)

    # ------------------------------------------------------------ verify
    def _build_verify_page(self) -> QWidget:
        page, body = self._page("Verify", "Checks that each tool runs, then compiles and runs a test program.",
                                self._action("Check tools", self.check_tools),
                                self._action("Compile test programs", self.smoke_test, primary=True))
        frame, lay = ui.card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self.verify_rows: dict[str, tuple[ui.Dot, object]] = {}
        titles = [t for t, _, _ in VERIFY_TOOLS] + (["PATH order"] if system.IS_WINDOWS else [])
        for i, title in enumerate(titles):
            dot = ui.Dot()
            value = ui.label("not checked", "faint")
            value.setFont(ui.mono_font(9))
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(dot, i, 0)
            grid.addWidget(ui.label(title), i, 1)
            grid.addWidget(value, i, 2)
            self.verify_rows[title] = (dot, value)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)
        body.addWidget(frame)
        body.addStretch(1)
        return page

    def check_tools(self) -> None:
        def job():
            system.refresh_process_path()
            env = system.toolchain_env()
            results = {}
            for title, exe, args in VERIFY_TOOLS:
                if exe in ("{gcc}", "{g++}"):
                    path = toolchain.find_compiler("c" if exe == "{gcc}" else "cpp")
                elif exe == "code":
                    path = system.find_code_cli()
                else:
                    path = system.find_tool(exe)
                if not path:
                    results[title] = (False, "not found")
                    continue
                rc, out = system.run_capture([path, *args], env=env)
                results[title] = (rc == 0, system.first_line(out) or f"exit {rc}")
            if system.IS_WINDOWS:
                conflicts = system.path_conflicts()
                results["PATH order"] = (None, conflicts[0] if conflicts else "GCC from MSYS2 comes first")
                for c in conflicts:
                    self.tasks.log("warning: " + c + ". Remove the other one from PATH or use Static link.")
            return results

        def done(results):
            if not isinstance(results, dict):
                return
            for title, (ok, text) in results.items():
                if title == "PATH order":
                    ok = text.startswith("GCC from MSYS2")
                    self.verify_rows[title][0].set("ok" if ok else "warn")
                    self.verify_rows[title][1].setText(text[:100])
                    continue
                dot, value = self.verify_rows[title]
                dot.set("ok" if ok else "missing")
                value.setText(text[:100])
                value.setProperty("role", None if ok else "faint")
                value.style().unpolish(value)
                value.style().polish(value)
            found = sum(ok for ok, _ in results.values() if ok is not None)
            self.console.write(f"{found}/{len(VERIFY_TOOLS)} tools found.", "ok" if found else "warn")
        self.tasks.run("Checking tools...", job, done)

    def smoke_test(self) -> None:
        programs = {
            "c": ("test.c", '#include <stdio.h>\nint main(void){printf("C works (%ld)\\n", __STDC_VERSION__);return 0;}\n'),
            "cpp": ("test.cpp", '#include <iostream>\n#include <vector>\nint main(){std::vector<int> v{1,2,3};'
                                'std::cout << "C++ works (" << __cplusplus << "), sum=" << v[0]+v[1]+v[2] << "\\n";}\n'),
        }

        def job():
            env = system.toolchain_env()
            with tempfile.TemporaryDirectory() as tmp:
                for lang, (fname, code) in programs.items():
                    info = toolchain.compiler_info(lang)
                    if info.is_clang:
                        self.tasks.log(f"warning: {info.path} is Clang, not GCC. Install GCC from the Classic pack.")
                    if not info.path:
                        self.tasks.log(f"error: {toolchain.compiler_name(lang)} not found. Install the Classic pack.")
                        continue
                    src = Path(tmp) / fname
                    src.write_text(code, encoding="utf-8")
                    opts = toolchain.BuildOptions(language=lang, standard=toolchain.DEFAULT_STANDARD[lang])
                    out = toolchain.output_path(src)
                    out.parent.mkdir(exist_ok=True)
                    if system.run_stream(toolchain.build_command(info.path, [src], out, opts), self.tasks.log, env=env) == 0:
                        rc = system.run_stream([out], self.tasks.log, env=env)
                        self.tasks.log(f"✓ {lang.upper()} toolchain OK." if rc == 0 else f"error: test program failed ({rc}).")
        self.tasks.run("Compiling test programs...", job)

    # ------------------------------------------------------------ shared
    def cancel(self) -> None:
        self.tasks.cancel()

    def _on_busy(self, busy: bool, text: str) -> None:
        self.status_label.setText(text if busy else "Ready")
        self.progress.setVisible(busy)
        self.b_cancel.setVisible(busy)
        self._update_action_states(busy)

    def _update_action_states(self, busy: bool | None = None) -> None:
        busy = self.tasks.busy if busy is None else busy
        for b in self.actions:
            b.setEnabled(not busy)
        if busy:
            return
        for key, (_, b) in self.rows.items():
            if self.status.get(key):
                b.setEnabled(False)
        for pack in PACKS:
            if pack.key in self.pack_buttons:
                comps = pack.available(system.PLATFORM, self.manager)
                if self.status and all(self.status.get(c.key) for c in comps):
                    self.pack_buttons[pack.key].setEnabled(False)

    def open_launcher(self) -> None:
        exe = sys.executable
        if system.IS_WINDOWS and exe.lower().endswith("python.exe"):
            exe = exe[:-len("python.exe")] + "pythonw.exe"
        subprocess.Popen([exe, str(HERE / "launcher_app.py")], cwd=HERE)


def main() -> int:
    app = ui.create_app("C/C++ DevKit Setup")
    window = SetupWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
