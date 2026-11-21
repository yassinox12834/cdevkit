"""C/C++ DevKit Launcher: pick a .c or .cpp file, choose the standard, build and run with GCC.

Run with launcher.bat (Windows) or:  python launcher_app.py
Shortcuts: Ctrl+O open, Ctrl+B build, F5 run (rebuilds if needed), Shift+F5 stop.
"""

from __future__ import annotations

import codecs
import subprocess
import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from devkit import system, toolchain, ui

FILE_TYPES = [
    ("C and C++ sources", "*.c *.cpp *.cc *.cxx *.c++"),
    ("C sources", "*.c"),
    ("C++ sources", "*.cpp *.cc *.cxx *.c++"),
    ("All files", "*.*"),
]

LANG_LABEL = {"c": "C", "cpp": "C++"}
LABEL_LANG = {v: k for k, v in LANG_LABEL.items()}


class LauncherApp:
    def __init__(self):
        self.root = ui.init_app("C/C++ DevKit Launcher", "1180x760", (980, 620))
        self.settings = system.Settings("launcher")
        self.proc: subprocess.Popen | None = None
        self.file: Path | None = None
        self.gcc_major = 0

        s = self.settings
        self.v_lang = ctk.StringVar(value=LANG_LABEL[s.get("language", "cpp")])
        self.std_by_lang: dict[str, str] = dict(toolchain.DEFAULT_STANDARD, **s.get("standards", {}))
        self.v_std = ctk.StringVar(value=self.std_by_lang[s.get("language", "cpp")])
        self.v_opt = ctk.StringVar(value=s.get("optimisation", "-O0"))
        self.v_warn = ctk.BooleanVar(value=s.get("warnings", True))
        self.v_debug = ctk.BooleanVar(value=s.get("debug", True))
        self.v_werror = ctk.BooleanVar(value=s.get("werror", False))
        self.v_ub = ctk.BooleanVar(value=s.get("ub_trap", False))
        self.v_static = ctk.BooleanVar(value=s.get("static", False))
        self.v_gnu = ctk.BooleanVar(value=s.get("gnu", False))
        self.v_folder = ctk.BooleanVar(value=s.get("whole_folder", False))
        self.v_external = ctk.BooleanVar(value=s.get("external", False))

        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_panel()
        self._build_output()

        self.tasks = ui.TaskRunner(self.root, self.console, self._on_busy)

        for var in (self.v_std, self.v_opt, self.v_warn, self.v_debug, self.v_werror, self.v_ub,
                    self.v_static, self.v_gnu, self.v_folder):
            var.trace_add("write", lambda *_: self._update_preview())
        self.extra.bind("<KeyRelease>", lambda _: self._update_preview())

        self.root.bind("<Control-o>", lambda _: self.browse())
        self.root.bind("<Control-b>", lambda _: self.build())
        self.root.bind("<F5>", lambda _: self.run())
        self.root.bind("<Shift-F5>", lambda _: self.stop())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        last = s.get("file")
        if last and Path(last).is_file():
            self.set_file(Path(last))
        else:
            self._update_preview()
        self.console.write("Open a .c or .cpp file (Ctrl+O), then press F5 to build and run.", "muted")
        self.tasks.run("Looking for GCC...", lambda: toolchain.compiler_info("cpp"), self._show_compiler)

    # ------------------------------------------------------------ layout
    def _build_header(self) -> None:
        head = ctk.CTkFrame(self.root, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(18, 10))
        head.grid_columnconfigure(1, weight=1)
        ui.label(head, "Launcher", "title").grid(row=0, column=0, sticky="w")
        self.compiler_pill = ctk.CTkLabel(head, text="GCC: checking...", font=ui.font("small"),
                                          text_color=ui.MUTED, fg_color=ui.SURFACE_2, corner_radius=6, padx=10)
        self.compiler_pill.grid(row=0, column=1, sticky="w", padx=14)

        bar = ctk.CTkFrame(head, fg_color="transparent")
        bar.grid(row=0, column=2, sticky="e")
        self.b_build = ui.button(bar, "Build  Ctrl+B", self.build, width=120)
        self.b_build.pack(side="left", padx=(0, 8))
        self.b_run = ui.button(bar, "Run  F5", self.run, primary=True, width=110)
        self.b_run.pack(side="left", padx=(0, 8))
        self.b_stop = ui.button(bar, "Stop", self.stop, width=70, state="disabled")
        self.b_stop.pack(side="left")

    def _field(self, parent, text: str) -> None:
        ui.label(parent, text.upper(), "label", ui.MUTED).pack(anchor="w", padx=16, pady=(14, 6))

    def _build_panel(self) -> None:
        panel = ctk.CTkScrollableFrame(self.root, width=360, fg_color=ui.SURFACE, corner_radius=10, border_width=1,
                                       border_color=ui.BORDER, scrollbar_button_color=ui.BORDER)
        panel.grid(row=1, column=0, sticky="nsw", padx=(20, 12), pady=(0, 20))

        # File
        self._field(panel, "Source file")
        self.file_label = ui.label(panel, "No file selected", "body", ui.FAINT, wraplength=330)
        self.file_label.pack(anchor="w", padx=16)
        self.file_dir = ui.label(panel, "", "small", ui.FAINT, wraplength=330)
        self.file_dir.pack(anchor="w", padx=16, pady=(0, 8))
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=16)
        ui.button(row, "Open file...", self.browse, width=110).pack(side="left", padx=(0, 8))
        self.v_recent = ctk.StringVar(value="Recent")
        self.recent_menu = ui.option_menu(row, self._recent_names() or ["(none)"], self.v_recent,
                                          self._open_recent, width=110)
        self.recent_menu.pack(side="left", padx=(0, 8))
        ui.button(row, "Edit", self.edit_in_vscode, width=60).pack(side="left")

        # Language & standard
        self._field(panel, "Language and standard")
        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=16)
        ui.segmented(row, ["C", "C++"], self.v_lang, self._lang_changed).pack(side="left", padx=(0, 10))
        lang = LABEL_LANG[self.v_lang.get()]
        self.std_menu = ui.option_menu(row, toolchain.STANDARDS[lang], self.v_std, self._std_changed, width=110)
        self.std_menu.pack(side="left")
        ui.switch(panel, "GNU extensions (gnu17 instead of c17)", self.v_gnu).pack(anchor="w", padx=16, pady=(10, 0))

        # Optimisation
        self._field(panel, "Optimisation")
        ui.segmented(panel, toolchain.OPTIMISATIONS, self.v_opt).pack(anchor="w", padx=16)
        ui.label(panel, "-O0 for debugging, -O2 for speed.", "small", ui.FAINT).pack(anchor="w", padx=16, pady=(4, 0))

        # Checks
        self._field(panel, "Compiler checks")
        for text, var in (("Warnings  -Wall -Wextra -Wpedantic", self.v_warn),
                          ("Treat warnings as errors  -Werror", self.v_werror),
                          ("Debug information  -g", self.v_debug),
                          ("Stop on undefined behaviour", self.v_ub)):
            ui.switch(panel, text, var).pack(anchor="w", padx=16, pady=3)

        # Build
        self._field(panel, "Build")
        ui.switch(panel, "Compile every file in the folder", self.v_folder).pack(anchor="w", padx=16, pady=3)
        if not system.IS_MAC:  # macOS does not allow fully static executables
            ui.switch(panel, "Static link (exe runs anywhere)", self.v_static).pack(anchor="w", padx=16, pady=3)
        else:
            self.v_static.set(False)
        ui.label(panel, "Extra flags", "small", ui.MUTED).pack(anchor="w", padx=16, pady=(8, 2))
        self.extra = ui.entry(panel, "-DDEBUG -Iinclude")
        self.extra.pack(fill="x", padx=16)
        if self.settings.get("extra_flags"):
            self.extra.insert(0, self.settings.get("extra_flags"))

        # Run
        self._field(panel, "Run")
        ui.label(panel, "Arguments", "small", ui.MUTED).pack(anchor="w", padx=16, pady=(0, 2))
        self.args = ui.entry(panel, "arg1 arg2")
        self.args.pack(fill="x", padx=16)
        if self.settings.get("args"):
            self.args.insert(0, self.settings.get("args"))
        ui.switch(panel, "Run in a separate terminal", self.v_external).pack(anchor="w", padx=16, pady=(10, 0))
        ui.label(panel, "Use it for programs that ask for input (scanf, std::cin), or fill the input box.",
                 "small", ui.FAINT, wraplength=330).pack(anchor="w", padx=16, pady=(2, 0))
        ui.label(panel, "Input (sent to stdin)", "small", ui.MUTED).pack(anchor="w", padx=16, pady=(8, 2))
        self.stdin_box = ctk.CTkTextbox(panel, height=70, fg_color=ui.SURFACE_2, border_color=ui.BORDER,
                                        border_width=1, corner_radius=7, font=ui.font("mono"), text_color=ui.TEXT)
        self.stdin_box.pack(fill="x", padx=16, pady=(0, 18))

    def _build_output(self) -> None:
        right = ctk.CTkFrame(self.root, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(0, 20), pady=(0, 20))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        prev = ui.card(right)
        prev.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        prev.grid_columnconfigure(0, weight=1)
        ui.label(prev, "COMMAND", "label", ui.MUTED).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        self.preview = ui.label(prev, "", "mono", ui.MUTED, wraplength=700)
        self.preview.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 12))
        prev.bind("<Configure>", lambda e: self.preview.configure(wraplength=max(200, e.width - 30)))

        self.console = ui.Console(right, "Output  (double-click an error to open it)", height=300)
        self.console.grid(row=1, column=0, sticky="nsew")

        status = ctk.CTkFrame(right, fg_color="transparent")
        status.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        status.grid_columnconfigure(1, weight=1)
        self.status_dot = ui.Dot(status, "missing")
        self.status_dot.grid(row=0, column=0, padx=(2, 6))
        self.status_label = ui.label(status, "Ready", "small", ui.MUTED)
        self.status_label.grid(row=0, column=1, sticky="w")

    # ------------------------------------------------------------ state
    def _show_compiler(self, info) -> None:
        if not isinstance(info, toolchain.CompilerInfo) or not info.path:
            self.compiler_pill.configure(text="GCC not found: install the Classic pack", text_color=ui.ERR)
        elif info.is_clang:
            self.compiler_pill.configure(text="Only Apple Clang found: install GCC from the Classic pack",
                                         text_color=ui.WARN)
        else:
            self.gcc_major = toolchain.gcc_major(info.version)
            self.compiler_pill.configure(text=f"GCC {info.version}", text_color=ui.OK)
            self._lang_changed(self.v_lang.get())  # hide standards this GCC cannot compile
        self._update_preview()

    def _lang(self) -> str:
        return LABEL_LANG[self.v_lang.get()]

    def _lang_changed(self, value: str) -> None:
        lang = LABEL_LANG[value]
        allowed = toolchain.supported_standards(lang, self.gcc_major)
        self.std_menu.configure(values=allowed)
        wanted = self.std_by_lang[lang]
        self.v_std.set(wanted if wanted in allowed else toolchain.DEFAULT_STANDARD[lang])
        self._update_preview()

    def _std_changed(self, value: str) -> None:
        self.std_by_lang[self._lang()] = value

    def options(self) -> toolchain.BuildOptions:
        return toolchain.BuildOptions(
            language=self._lang(), standard=self.v_std.get(), optimisation=self.v_opt.get(),
            warnings=self.v_warn.get(), debug=self.v_debug.get(), werror=self.v_werror.get(),
            ub_trap=self.v_ub.get(), static=self.v_static.get(), gnu=self.v_gnu.get(),
            extra_flags=self.extra.get(), gcc_major=self.gcc_major,
        )

    def _command(self) -> tuple[list[str], Path, list[Path]] | None:
        if not self.file:
            return None
        lang = self._lang()
        compiler = toolchain.find_compiler(lang) or toolchain.compiler_name(lang)
        sources = toolchain.collect_sources(self.file, self.v_folder.get())
        out = toolchain.output_path(self.file)
        return toolchain.build_command(compiler, sources, out, self.options()), out, sources

    def _update_preview(self) -> None:
        built = self._command()
        if not built:
            self.preview.configure(text="Open a file to see the GCC command.")
            return
        cmd, _, _ = built
        shown = [Path(cmd[0]).name] + [self._short(c) for c in cmd[1:]]
        self.preview.configure(text=system.format_cmd(shown))

    def _short(self, arg: str) -> str:
        """Show paths relative to the source folder, so the preview stays readable."""
        if self.file:
            try:
                return str(Path(arg).relative_to(self.file.parent))
            except ValueError:
                pass
        return arg

    # ------------------------------------------------------------- files
    def browse(self) -> None:
        initial = str(self.file.parent) if self.file else None
        chosen = filedialog.askopenfilename(title="Choose a C or C++ file", filetypes=FILE_TYPES, initialdir=initial)
        if chosen:
            self.set_file(Path(chosen))

    def set_file(self, path: Path) -> None:
        lang = toolchain.detect_language(path)
        if lang is None:
            self.console.write(f"warning: {path.name} is not a .c or .cpp file. Choose the language yourself.", "warn")
        elif lang != self._lang():
            self.v_lang.set(LANG_LABEL[lang])
            self._lang_changed(LANG_LABEL[lang])
        self.file = path
        self.file_label.configure(text=path.name, text_color=ui.TEXT)
        self.file_dir.configure(text=str(path.parent))
        recent = [str(path)] + [r for r in self.settings.get("recent", []) if r != str(path)]
        self.settings.set("recent", recent[:8])
        self.recent_menu.configure(values=self._recent_names() or ["(none)"])
        self.v_recent.set("Recent")
        self._update_preview()
        self._save()

    def _recent_names(self) -> list[str]:
        return [Path(r).name + "  ·  " + Path(r).parent.name for r in self.settings.get("recent", [])]

    def _open_recent(self, choice: str) -> None:
        names = self._recent_names()
        if choice in names:
            path = Path(self.settings.get("recent")[names.index(choice)])
            if path.is_file():
                self.set_file(path)
            else:
                self.console.write(f"error: {path} no longer exists.", "err")
        self.v_recent.set("Recent")

    def edit_in_vscode(self) -> None:
        if self.file and not system.open_in_vscode(self.file):
            self.console.write("VS Code not found. Install the Classic pack.", "warn")

    # ------------------------------------------------------- build & run
    def _needs_build(self, out: Path, sources: list[Path]) -> bool:
        if not out.exists():
            return True
        built_at = out.stat().st_mtime
        headers = [p for p in self.file.parent.glob("*.h*") if p.is_file()] if self.file else []
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
        args = toolchain.split_flags(self.args.get())
        stdin_text = self.stdin_box.get("1.0", "end-1c")
        external = self.v_external.get()

        def job():
            if self._needs_build(out, sources) and not self._compile(cmd, out):
                return
            if external:
                self._run_external(out, args)
            else:
                self._run_captured(out, args, stdin_text)
        self.tasks.run("Running...", job)

    def _ready(self):
        if self.tasks.busy:
            return None
        if not self.file:
            self.browse()
            if not self.file:
                return None
        if not self.file.is_file():
            self.console.write(f"error: {self.file} no longer exists.", "err")
            return None
        self._save()
        self.console.clear()
        return self._command()

    def _run_external(self, exe: Path, args: list[str]) -> None:
        cwd = self.file.parent
        if system.IS_WINDOWS:
            line = " ".join(subprocess.list2cmdline([a]) for a in [str(exe), *args])
            # The outer quotes are removed by cmd /c; call + %^errorlevel% reads the code after the run.
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
        self.tasks.ui(lambda: (self.b_stop.configure(state="normal"), self._set_status("busy", "Running...")))

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
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
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
        self.tasks.ui(lambda: (self.b_stop.configure(state="disabled"),
                               self._set_status(state, f"Finished: {desc}")))

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.console.write("Stopped by you.", "warn")

    # ------------------------------------------------------------ shared
    def _set_status(self, state: str, text: str) -> None:
        self.status_dot.set(state)
        self.status_label.configure(text=text)

    def _on_busy(self, busy: bool, text: str) -> None:
        for b in (self.b_build, self.b_run):
            b.configure(state="disabled" if busy else "normal")
        if not busy:
            self.b_stop.configure(state="disabled")

    def _save(self) -> None:
        s = self.settings
        s.set("file", str(self.file) if self.file else None)
        s.set("language", self._lang())
        s.set("standards", self.std_by_lang)
        for key, var in (("optimisation", self.v_opt), ("warnings", self.v_warn), ("debug", self.v_debug),
                         ("werror", self.v_werror), ("ub_trap", self.v_ub), ("static", self.v_static),
                         ("gnu", self.v_gnu), ("whole_folder", self.v_folder), ("external", self.v_external)):
            s.set(key, var.get())
        s.set("extra_flags", self.extra.get())
        s.set("args", self.args.get())
        s.save()

    def _on_close(self) -> None:
        self.stop()
        self._save()
        self.root.destroy()


def main() -> ctk.CTk:
    return LauncherApp().root


if __name__ == "__main__":
    ui.run_app(main)
