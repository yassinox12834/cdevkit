"""C/C++ DevKit Setup: install packs, configure them, verify the toolchain.

Run with setup.bat (Windows) or:  python setup_app.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from devkit import __version__, configure, system, toolchain, ui
from devkit.installer import Installer
from devkit.packs import ALL_COMPONENTS, PACKS, Component, Pack
from devkit.project_template import create_project
from devkit.vscode_settings import apply_toolchain_settings

HERE = Path(__file__).resolve().parent

BG_TRANSPARENT = "transparent"

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


class SetupApp:
    def __init__(self):
        self.root = ui.init_app("C/C++ DevKit Setup", "1180x780", (1000, 660))
        self.status: dict[str, bool] = {}
        self.rows: dict[str, tuple[ui.Dot, ctk.CTkButton]] = {}
        self.pack_buttons: dict[str, ctk.CTkButton] = {}
        self.actions: list[ctk.CTkButton] = []

        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        main = ctk.CTkFrame(self.root, fg_color=BG_TRANSPARENT)
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 18), pady=18)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        self.pages_host = ctk.CTkFrame(main, fg_color=BG_TRANSPARENT)
        self.pages_host.grid(row=0, column=0, sticky="nsew")
        self.pages_host.grid_columnconfigure(0, weight=1)
        self.pages_host.grid_rowconfigure(0, weight=1)

        bottom = ctk.CTkFrame(main, fg_color=BG_TRANSPARENT)
        bottom.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        bottom.grid_columnconfigure(0, weight=1)
        status_row = ctk.CTkFrame(bottom, fg_color=BG_TRANSPARENT)
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        status_row.grid_columnconfigure(1, weight=1)
        self.status_label = ui.label(status_row, "Ready", "small", ui.MUTED)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.progress = ctk.CTkProgressBar(status_row, height=4, progress_color=ui.ACCENT, fg_color=ui.BORDER,
                                           mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=(14, 0))
        self.progress.set(0)
        self.console = ui.Console(bottom, "Log", height=120)
        self.console.grid(row=1, column=0, sticky="ew")

        self.tasks = ui.TaskRunner(self.root, self.console, self._on_busy)
        self.installer = Installer(self.tasks.log)
        self.manager = self.installer.manager

        self.pages = {
            "packs": self._build_packs_page(),
            "configure": self._build_configure_page(),
            "verify": self._build_verify_page(),
        }
        self.show("packs")

        if system.IS_LINUX and not self.manager:
            self.console.write("warning: no apt, dnf or pacman found. Only VS Code extensions can be installed.", "warn")
        where = f"{system.PLATFORM_NAME} ({self.manager})" if self.manager else system.PLATFORM_NAME
        self.console.write(f"Detected {where}. Start with the Classic pack: GCC, CMake, Git and VS Code.", "muted")
        self.refresh_status()

    # ------------------------------------------------------------ layout
    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self.root, fg_color=ui.SIDEBAR, corner_radius=0, width=230)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        ui.label(side, "C/C++ DevKit", "title").pack(anchor="w", padx=22, pady=(24, 0))
        ui.label(side, f"GCC toolchain for {system.PLATFORM_NAME}", "small", ui.MUTED).pack(anchor="w", padx=22, pady=(2, 26))

        self.nav: dict[str, ctk.CTkButton] = {}
        for key, text in (("packs", "Packs"), ("configure", "Configure"), ("verify", "Verify")):
            b = ctk.CTkButton(side, text=text, anchor="w", height=36, corner_radius=7, font=ui.font("body"),
                              fg_color="transparent", hover_color=ui.SURFACE_2, text_color=ui.MUTED,
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav[key] = b

        ctk.CTkFrame(side, fg_color="transparent").pack(fill="both", expand=True)
        ui.button(side, "Open code launcher", self.open_launcher, primary=True).pack(fill="x", padx=16, pady=(0, 10))
        ui.label(side, f"v{__version__}", "small", ui.FAINT).pack(anchor="w", padx=22, pady=(0, 16))

    def show(self, key: str) -> None:
        for name, page in self.pages.items():
            page.grid_forget() if name != key else page.grid(row=0, column=0, sticky="nsew")
        for name, b in self.nav.items():
            active = name == key
            b.configure(fg_color=ui.SURFACE_2 if active else "transparent", text_color=ui.TEXT if active else ui.MUTED)

    def _page(self, title: str, subtitle: str) -> tuple[ctk.CTkFrame, ctk.CTkScrollableFrame]:
        page = ctk.CTkFrame(self.pages_host, fg_color=BG_TRANSPARENT)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(page, fg_color=BG_TRANSPARENT)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        head.grid_columnconfigure(0, weight=1)
        ui.label(head, title, "title").grid(row=0, column=0, sticky="w")
        ui.label(head, subtitle, "small", ui.MUTED).grid(row=1, column=0, sticky="w")
        body = ctk.CTkScrollableFrame(page, fg_color=BG_TRANSPARENT, scrollbar_button_color=ui.BORDER,
                                      scrollbar_button_hover_color=ui.FAINT)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        page.head = head  # type: ignore[attr-defined]
        return page, body

    def _action(self, *args, **kwargs) -> ctk.CTkButton:
        b = ui.button(*args, **kwargs)
        self.actions.append(b)
        return b

    # ------------------------------------------------------------- packs
    def _build_packs_page(self) -> ctk.CTkFrame:
        page, body = self._page("Packs", "Pick what to install. Already installed items are skipped.")
        self._action(page.head, "Refresh status", self.refresh_status, width=130).grid(row=0, column=1, rowspan=2)

        for i, pack in enumerate(PACKS):
            c = ui.card(body)
            c.grid(row=i, column=0, sticky="ew", pady=(0, 12), padx=(0, 6))
            c.grid_columnconfigure(0, weight=1)

            head = ctk.CTkFrame(c, fg_color="transparent")
            head.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
            head.grid_columnconfigure(0, weight=1)
            title_row = ctk.CTkFrame(head, fg_color="transparent")
            title_row.grid(row=0, column=0, sticky="w")
            ui.label(title_row, pack.title, "heading").pack(side="left")
            if pack.recommended:
                ctk.CTkLabel(title_row, text="RECOMMENDED", font=ui.font("label"), text_color=ui.ACCENT,
                             fg_color=ui.SURFACE_2, corner_radius=5, padx=6).pack(side="left", padx=10)
            ui.label(head, pack.subtitle, "small", ui.MUTED).grid(row=1, column=0, sticky="w")
            pb = self._action(head, "Install pack", lambda p=pack: self.install_pack(p), primary=pack.recommended,
                              width=120)
            pb.grid(row=0, column=1, rowspan=2, sticky="e")
            self.pack_buttons[pack.key] = pb

            comps = pack.available(system.PLATFORM, self.manager)
            for j, comp in enumerate(comps):
                self._component_row(c, comp, j + 1, last=j == len(comps) - 1)
        return page

    def _component_row(self, parent, comp: Component, row: int, last: bool) -> None:
        ctk.CTkFrame(parent, height=1, fg_color=ui.BORDER).grid(row=row * 2 - 1, column=0, sticky="ew", padx=18)
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.grid(row=row * 2, column=0, sticky="ew", padx=18, pady=(6, 12 if last else 6))
        r.grid_columnconfigure(2, weight=1)
        r.grid_columnconfigure(0, minsize=48)
        ui.tile(r, comp.mono, comp.category).grid(row=0, column=0, rowspan=2, sticky="w")
        ui.label(r, comp.name, "body").grid(row=0, column=1, sticky="w")
        method = comp.source(system.PLATFORM, self.manager)[0]
        ctk.CTkLabel(r, text=METHOD_LABEL.get(method, self.manager or ""), font=ui.font("small"),
                     text_color=ui.FAINT).grid(row=0, column=2, sticky="w", padx=10)
        dot = ui.Dot(r)
        dot.grid(row=0, column=3, rowspan=2, padx=(0, 10))
        ui.label(r, comp.summary, "small", ui.MUTED).grid(row=1, column=1, columnspan=2, sticky="w")
        b = self._action(r, "Install", lambda c=comp: self.install_one(c), width=96)
        b.grid(row=0, column=4, rowspan=2, sticky="e")
        self.rows[comp.key] = (dot, b)

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
            b.configure(text="Installed" if ok else "Install")
        for pack in PACKS:
            comps = pack.available(system.PLATFORM, self.manager)
            missing = sum(not result.get(c.key) for c in comps)
            self.pack_buttons[pack.key].configure(text="Installed" if missing == 0 else f"Install pack ({missing})")
        self._update_action_states()

    def install_one(self, comp: Component) -> None:
        def job():
            ok = self.installer.install(comp)
            self.installer.post_configure([comp])
            return ok
        self.rows[comp.key][0].set("busy")
        self.tasks.run(f"Installing {comp.name}...", job, lambda _: self.refresh_status())

    def install_pack(self, pack: Pack) -> None:
        def job():
            done, failed = self.installer.install_pack(pack)
            self.tasks.log(f"── {pack.title}: {done} ok, {failed} failed ──")
            if failed == 0:
                self.tasks.log("✓ Done. Open a NEW terminal or restart VS Code so they see the new PATH.")
        self.tasks.run(f"Installing {pack.title}...", job, lambda _: self.refresh_status())

    # --------------------------------------------------------- configure
    def _section(self, body, row: int, title: str, text: str) -> ctk.CTkFrame:
        c = ui.card(body)
        c.grid(row=row, column=0, sticky="ew", pady=(0, 12), padx=(0, 6))
        c.grid_columnconfigure(0, weight=1)
        ui.label(c, title, "heading").grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        ui.label(c, text, "small", ui.MUTED, wraplength=760).grid(row=1, column=0, sticky="w", padx=18, pady=(2, 10))
        inner = ctk.CTkFrame(c, fg_color="transparent")
        inner.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        return inner

    def _build_configure_page(self) -> ctk.CTkFrame:
        page, body = self._page("Configure", "Settings applied after installing. Each button is safe to click twice.")

        # Toolchain
        path_text = {
            "windows": "Puts GCC's folder on your PATH so every terminal and VS Code can find it, "
                       "and points VS Code's C/C++ extension at GCC.",
            "macos": "Adds Homebrew to your shell profile so Terminal and VS Code find GCC, "
                     "and points VS Code's C/C++ extension at Homebrew's GCC instead of Apple Clang.",
            "linux": "Linux packages already land on PATH, so this only points VS Code's C/C++ extension at GCC.",
        }[system.PLATFORM]
        t = self._section(body, 0, "Toolchain", path_text)
        self.path_dot = ui.Dot(t)
        self.path_dot.pack(side="left", padx=(0, 6))
        self.path_label = ui.label(t, "", "small", ui.MUTED)
        self.path_label.pack(side="left", padx=(0, 14))
        if not system.IS_LINUX:
            self._action(t, "Add to PATH", self.add_path).pack(side="left", padx=(0, 8))
        self._action(t, "Configure VS Code for GCC", self.configure_vscode).pack(side="left")
        self._update_path_label()

        # Git
        g = self._section(body, 1, "Git identity",
                          "Every commit is signed with this name and email. Use your GitHub email.")
        g.grid_columnconfigure((0, 1), weight=1)
        self.git_name = ui.entry(g, "Your name")
        self.git_name.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.git_email = ui.entry(g, "you@example.com")
        self.git_email.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self._action(g, "Save identity", self.save_git_identity, primary=True).grid(row=0, column=2)
        self._action(g, "Apply recommended Git settings", self.git_defaults).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.tasks.run("Reading Git config...",
                       lambda: (configure.git_get("user.name"), configure.git_get("user.email")),
                       self._fill_git)

        # GitHub
        h = self._section(body, 2, "GitHub",
                          "Sign in once with the GitHub CLI; Git then pushes without asking for a password. "
                          "Needs GitHub CLI from the Extras pack.")
        self._action(h, "Sign in to GitHub", lambda: configure.github_login(self.tasks.log), primary=True).pack(
            side="left", padx=(0, 8))
        self._action(h, "Check sign-in", lambda: self.tasks.run(
            "Checking GitHub...", lambda: configure.github_status(self.tasks.log))).pack(side="left", padx=(0, 8))
        self._action(h, "New repository on github.com", configure.open_new_repo_page).pack(side="left", padx=(0, 8))
        self._action(h, "Install GitHub CLI", lambda: self.install_one(ALL_COMPONENTS["gh"])).pack(side="left")

        # New project
        p = self._section(body, 3, "New project",
                          "Creates a CMake project with VS Code build (Ctrl+Shift+B) and debug (F5) "
                          "already set up, plus .clang-format, .gitignore and git init.")
        p.grid_columnconfigure(1, weight=1)
        ui.label(p, "Location", "small", ui.MUTED).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.proj_dir = ui.entry(p, "Choose a parent folder")
        self.proj_dir.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ui.button(p, "Browse", self.pick_project_dir, width=80).grid(row=0, column=2)

        ui.label(p, "Name", "small", ui.MUTED).grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.proj_name = ui.entry(p, "my_project")
        self.proj_name.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(10, 0))

        opts = ctk.CTkFrame(p, fg_color="transparent")
        opts.grid(row=2, column=1, sticky="w", pady=(10, 0))
        self.proj_lang = ctk.StringVar(value="C++")
        self.proj_std = ctk.StringVar(value=toolchain.DEFAULT_STANDARD["cpp"])
        ui.segmented(opts, ["C", "C++"], self.proj_lang, self._proj_lang_changed).pack(side="left", padx=(0, 10))
        self.proj_std_menu = ui.option_menu(opts, toolchain.CPP_STANDARDS, self.proj_std, width=110)
        self.proj_std_menu.pack(side="left", padx=(0, 10))
        self.proj_open = ctk.BooleanVar(value=True)
        ui.switch(opts, "Open in VS Code", self.proj_open).pack(side="left", padx=(6, 0))
        self._action(p, "Create project", self.create_project, primary=True).grid(row=3, column=1, sticky="w",
                                                                                  pady=(12, 0))
        return page

    def _fill_git(self, result) -> None:
        if isinstance(result, tuple):
            name, email = result
            if name:
                self.git_name.insert(0, name)
            if email:
                self.git_email.insert(0, email)

    def _update_path_label(self) -> None:
        state, text = system.path_status()
        self.path_dot.set(state)
        self.path_label.configure(text=text)

    def add_path(self) -> None:
        self.tasks.run("Updating PATH...", lambda: system.configure_path(self.tasks.log),
                       lambda _: self._update_path_label())

    def configure_vscode(self) -> None:
        def job():
            self.installer.invalidate()
            apply_toolchain_settings(self.tasks.log, use_clangd=self.installer.is_installed(ALL_COMPONENTS["ext-clangd"]))
        self.tasks.run("Configuring VS Code...", job)

    def save_git_identity(self) -> None:
        name, email = self.git_name.get(), self.git_email.get()
        self.tasks.run("Saving Git identity...", lambda: configure.set_git_identity(name, email, self.tasks.log))

    def git_defaults(self) -> None:
        self.tasks.run("Applying Git settings...", lambda: configure.apply_git_defaults(self.tasks.log))

    def _proj_lang_changed(self, value: str) -> None:
        lang = "c" if value == "C" else "cpp"
        self.proj_std_menu.configure(values=toolchain.STANDARDS[lang])
        self.proj_std.set(toolchain.DEFAULT_STANDARD[lang])

    def pick_project_dir(self) -> None:
        folder = filedialog.askdirectory(title="Where should the project folder go?")
        if folder:
            self.proj_dir.delete(0, "end")
            self.proj_dir.insert(0, folder)

    def create_project(self) -> None:
        parent = self.proj_dir.get().strip()
        name = self.proj_name.get().strip() or "my_project"
        if not parent or not Path(parent).is_dir():
            self.console.write("error: choose an existing parent folder first.", "err")
            return
        lang = "c" if self.proj_lang.get() == "C" else "cpp"
        std, open_it = self.proj_std.get(), self.proj_open.get()

        def job():
            dest = create_project(Path(parent), name, lang, std, self.tasks.log)
            if dest and open_it and not system.open_in_vscode(dest):
                self.tasks.log("VS Code not found, so the project was not opened.")
        self.tasks.run("Creating project...", job)

    # ------------------------------------------------------------ verify
    def _build_verify_page(self) -> ctk.CTkFrame:
        page, body = self._page("Verify", "Checks that each tool runs, then compiles and runs a test program.")
        bar = ctk.CTkFrame(page.head, fg_color="transparent")
        bar.grid(row=0, column=1, rowspan=2)
        self._action(bar, "Check tools", self.check_tools).pack(side="left", padx=(0, 8))
        self._action(bar, "Compile test programs", self.smoke_test, primary=True).pack(side="left")

        c = ui.card(body)
        c.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        c.grid_columnconfigure(2, weight=1)
        self.verify_rows: dict[str, tuple[ui.Dot, ctk.CTkLabel]] = {}
        for i, (title, _, _) in enumerate(VERIFY_TOOLS):
            dot = ui.Dot(c)
            dot.grid(row=i, column=0, padx=(18, 8), pady=(12 if i == 0 else 4, 12 if i == len(VERIFY_TOOLS) - 1 else 4))
            ui.label(c, title, "body").grid(row=i, column=1, sticky="w", padx=(0, 20))
            v = ui.label(c, "not checked", "mono", ui.FAINT)
            v.grid(row=i, column=2, sticky="w", padx=(0, 18))
            self.verify_rows[title] = (dot, v)
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
            return results

        def done(results):
            if not isinstance(results, dict):
                return
            for title, (ok, text) in results.items():
                dot, v = self.verify_rows[title]
                dot.set("ok" if ok else "missing")
                v.configure(text=text[:90], text_color=ui.TEXT if ok else ui.FAINT)
            found = sum(ok for ok, _ in results.values())
            self.console.write(f"{found}/{len(results)} tools found.", "ok" if found else "warn")
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
                    compiler = info.path
                    if info.is_clang:
                        self.tasks.log(f"warning: {compiler} is Clang, not GCC. Install GCC from the Classic pack.")
                    if not compiler:
                        self.tasks.log(f"error: {toolchain.compiler_name(lang)} not found. Install the Classic pack.")
                        continue
                    src = Path(tmp) / fname
                    src.write_text(code, encoding="utf-8")
                    opts = toolchain.BuildOptions(language=lang, standard=toolchain.DEFAULT_STANDARD[lang])
                    out = toolchain.output_path(src)
                    out.parent.mkdir(exist_ok=True)
                    if system.run_stream(toolchain.build_command(compiler, [src], out, opts), self.tasks.log, env=env) == 0:
                        rc = system.run_stream([out], self.tasks.log, env=env)
                        self.tasks.log(f"✓ {lang.upper()} toolchain OK." if rc == 0 else f"error: test program failed ({rc}).")
        self.tasks.run("Compiling test programs...", job)

    # ------------------------------------------------------------ shared
    def _on_busy(self, busy: bool, text: str) -> None:
        self.status_label.configure(text=text if busy else "Ready", text_color=ui.TEXT if busy else ui.MUTED)
        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)
        self._update_action_states(busy)

    def _update_action_states(self, busy: bool | None = None) -> None:
        busy = self.tasks.busy if busy is None else busy
        for b in self.actions:
            b.configure(state="disabled" if busy else "normal")
        if not busy:
            for key, (_, b) in self.rows.items():
                if self.status.get(key):
                    b.configure(state="disabled")
            for pack in PACKS:
                comps = pack.available(system.PLATFORM, self.manager)
                if self.status and all(self.status.get(c.key) for c in comps):
                    self.pack_buttons[pack.key].configure(state="disabled")

    def open_launcher(self) -> None:
        exe = sys.executable
        if system.IS_WINDOWS and exe.lower().endswith("python.exe"):
            exe = exe[:-len("python.exe")] + "pythonw.exe"
        subprocess.Popen([exe, str(HERE / "launcher_app.py")], cwd=HERE)



def main() -> ctk.CTk:
    return SetupApp().root


if __name__ == "__main__":
    ui.run_app(main)
