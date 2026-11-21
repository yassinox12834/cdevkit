"""Shared look and widgets for both apps: one sober dark theme, one accent colour."""

from __future__ import annotations

import queue
import re
import threading
import tkinter.font as tkfont
import traceback
from typing import Callable

import customtkinter as ctk

from . import system

# ------------------------------------------------------------------ palette
BG = "#0e1014"
SIDEBAR = "#12151a"
SURFACE = "#171a20"
SURFACE_2 = "#1d2129"
BORDER = "#262b34"
TEXT = "#e6e8eb"
MUTED = "#8a919c"
FAINT = "#5c636e"
ACCENT = "#4c8dff"
ACCENT_HOVER = "#3a78e6"
OK = "#3fb950"
WARN = "#d29922"
ERR = "#f26a63"

_fonts: dict[str, ctk.CTkFont] = {}


def _family(candidates: list[str]) -> str:
    available = set(tkfont.families())
    for name in candidates:
        if name in available:
            return name
    return candidates[-1]


def font(kind: str = "body") -> ctk.CTkFont:
    """Fonts are created lazily because they need a Tk root."""
    if kind not in _fonts:
        ui = _family(["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica"])
        mono = _family(["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Courier"])
        specs = {
            "title": (ui, 20, "bold"),
            "heading": (ui, 15, "bold"),
            "body": (ui, 13, "normal"),
            "small": (ui, 12, "normal"),
            "label": (ui, 11, "bold"),
            "mono": (mono, 12, "normal"),
        }
        fam, size, weight = specs[kind]
        _fonts[kind] = ctk.CTkFont(family=fam, size=size, weight=weight)
    return _fonts[kind]


def init_app(title: str, size: str, min_size: tuple[int, int]) -> ctk.CTk:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk(fg_color=BG)
    root.title(title)
    root.geometry(size)
    root.minsize(*min_size)
    return root


# ------------------------------------------------------------------ widgets
def card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER, **kw)


def label(parent, text: str = "", kind: str = "body", color: str = TEXT, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=font(kind), text_color=color, anchor="w", justify="left", **kw)


def button(parent, text: str, command=None, primary: bool = False, width: int = 0, **kw) -> ctk.CTkButton:
    style = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#ffffff") if primary else \
        dict(fg_color=SURFACE_2, hover_color=BORDER, text_color=TEXT, border_width=1, border_color=BORDER)
    if width:
        kw["width"] = width
    return ctk.CTkButton(parent, text=text, command=command, corner_radius=7, height=32,
                         font=font("body"), **style, **kw)


def entry(parent, placeholder: str = "", **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(parent, placeholder_text=placeholder, fg_color=SURFACE_2, border_color=BORDER,
                        border_width=1, corner_radius=7, height=32, text_color=TEXT, font=font("body"), **kw)


def switch(parent, text: str, variable, command=None) -> ctk.CTkSwitch:
    return ctk.CTkSwitch(parent, text=text, variable=variable, command=command, font=font("body"),
                         text_color=TEXT, progress_color=ACCENT, button_color="#dfe3ea",
                         button_hover_color="#ffffff", fg_color=BORDER, switch_width=34, switch_height=18)


def segmented(parent, values: list[str], variable, command=None) -> ctk.CTkSegmentedButton:
    return ctk.CTkSegmentedButton(parent, values=values, variable=variable, command=command, font=font("small"),
                                  fg_color=SURFACE_2, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                  unselected_color=SURFACE_2, unselected_hover_color=BORDER,
                                  text_color=TEXT, corner_radius=7, height=30)


def option_menu(parent, values: list[str], variable, command=None, width: int = 140) -> ctk.CTkOptionMenu:
    return ctk.CTkOptionMenu(parent, values=values, variable=variable, command=command, width=width, height=30,
                             fg_color=SURFACE_2, button_color=SURFACE_2, button_hover_color=BORDER,
                             dropdown_fg_color=SURFACE_2, dropdown_hover_color=BORDER, dropdown_text_color=TEXT,
                             text_color=TEXT, font=font("body"), dropdown_font=font("body"), corner_radius=7)


TILE_COLORS = {
    # category: (background, text): muted tints, one hue per kind of tool
    "toolchain": ("#1c2a44", "#8fb4ff"),
    "build": ("#2a2440", "#b9a4ff"),
    "editor": ("#162f38", "#7fd0e6"),
    "quality": ("#1d3326", "#7fd49a"),
    "github": ("#2b2b2f", "#d6d8dc"),
    "docs": ("#3a2c1a", "#e9b872"),
}


def tile(parent, letters: str, category: str, size: int = 34) -> ctk.CTkLabel:
    """A square two-letter monogram: a neutral stand-in for each tool's icon."""
    bg, fg = TILE_COLORS.get(category, (SURFACE_2, TEXT))
    return ctk.CTkLabel(parent, text=letters, width=size, height=size, corner_radius=8, fg_color=bg,
                        text_color=fg, font=ctk.CTkFont(family=font("label").cget("family"), size=12, weight="bold"))


class Dot(ctk.CTkLabel):
    """A small coloured status dot."""

    COLORS = {"ok": OK, "missing": FAINT, "warn": WARN, "error": ERR, "busy": ACCENT}

    def __init__(self, parent, state: str = "missing"):
        super().__init__(parent, text="●", font=font("small"), width=14)
        self.set(state)

    def set(self, state: str) -> None:
        self.configure(text_color=self.COLORS.get(state, FAINT))


# ----------------------------------------------------------------- console
_LOCATION = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+)(?::\d+)?:")


class Console(ctk.CTkFrame):
    """Read-only, colour-coded output panel. Double-click an error line to open it in VS Code."""

    MAX_LINES = 5000

    def __init__(self, parent, title: str = "Output", height: int = 160):
        super().__init__(parent, fg_color=SURFACE, corner_radius=10, border_width=1, border_color=BORDER)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 0))
        label(head, title.upper(), "label", MUTED).pack(side="left")
        ctk.CTkButton(head, text="Clear", width=50, height=22, fg_color="transparent", hover_color=SURFACE_2,
                      text_color=MUTED, font=font("small"), command=self.clear).pack(side="right")
        ctk.CTkButton(head, text="Copy", width=50, height=22, fg_color="transparent", hover_color=SURFACE_2,
                      text_color=MUTED, font=font("small"), command=self.copy).pack(side="right")

        self.text = ctk.CTkTextbox(self, height=height, fg_color=SURFACE, text_color=TEXT, font=font("mono"),
                                   wrap="word", border_width=0, activate_scrollbars=True)
        self.text.pack(fill="both", expand=True, padx=6, pady=(2, 8))
        for tag, color in (("cmd", ACCENT), ("err", ERR), ("warn", WARN), ("ok", OK), ("muted", MUTED)):
            self.text.tag_config(tag, foreground=color)
        self.text.configure(state="disabled")
        self.text.bind("<Double-Button-1>", self._on_double_click)

    @staticmethod
    def classify(line: str) -> str | None:
        low = line.lower()
        if line.startswith("$ "):
            return "cmd"
        if line.startswith("✓"):
            return "ok"
        if "error" in low or "fatal" in low or "undefined reference" in low:
            return "err"
        if "warning" in low:
            return "warn"
        if line.startswith("──") or "note:" in low:
            return "muted"
        return None

    def write(self, line: str, tag: str | None = None) -> None:
        tag = tag or self.classify(line)
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n", (tag,) if tag else ())
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self.text.delete("1.0", f"{lines - self.MAX_LINES}.0")
        self.text.see("end")
        self.text.configure(state="disabled")

    def write_raw(self, chunk: str) -> None:
        """Program output: no colour classification."""
        self.text.configure(state="normal")
        self.text.insert("end", chunk)
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end-1c"))

    def _on_double_click(self, event) -> str:
        index = self.text.index(f"@{event.x},{event.y}")
        line = self.text.get(f"{index} linestart", f"{index} lineend")
        m = _LOCATION.match(line.strip())
        if m:
            system.open_in_vscode(m.group("file"), int(m.group("line")))
        return "break"


# ------------------------------------------------------------- task runner
class TaskRunner:
    """Runs one blocking job at a time on a worker thread.

    Tkinter is not thread-safe, so the worker only puts messages on a queue and
    the UI thread reads them every 50 ms.
    """

    def __init__(self, root: ctk.CTk, console: Console, on_busy: Callable[[bool, str], None]):
        self.root = root
        self.console = console
        self.on_busy = on_busy
        self.busy = False
        self._q: queue.Queue = queue.Queue()
        self._pending: list = []
        self.root.after(50, self._poll)

    def log(self, line: str) -> None:          # safe from any thread
        self._q.put(("log", line))

    def raw(self, chunk: str) -> None:          # safe from any thread
        self._q.put(("raw", chunk))

    def ui(self, fn: Callable[[], None]) -> None:  # run fn on the UI thread
        self._q.put(("call", fn))

    def run(self, label_text: str, job: Callable[[], object], done: Callable[[object], None] | None = None) -> bool:
        if self.busy:
            self._pending.append((label_text, job, done))  # runs when the current job ends
            return False
        self.busy = True
        self.on_busy(True, label_text)

        def worker():
            result = None
            try:
                result = job()
            except Exception:  # noqa: BLE001  (show any failure in the console)
                for line in traceback.format_exc().rstrip().splitlines():
                    self.log("error: " + line if line.startswith("Traceback") else line)
            finally:
                self._q.put(("done", (done, result)))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _poll(self) -> None:
        try:
            for _ in range(500):
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self.console.write(payload)
                elif kind == "raw":
                    self.console.write_raw(payload)
                elif kind == "call":
                    payload()
                elif kind == "done":
                    self.busy = False
                    self.on_busy(False, "")
                    callback, result = payload
                    if callback:
                        callback(result)
                    if self._pending and not self.busy:
                        self.run(*self._pending.pop(0))
        except queue.Empty:
            pass
        self.root.after(50, self._poll)


def run_app(build: Callable[[], ctk.CTk]) -> None:
    """Start an app; if it crashes, write a log and show a message instead of vanishing."""
    try:
        build().mainloop()
    except Exception:  # noqa: BLE001
        log_file = system.APP_DIR / "crash.log"
        try:
            system.APP_DIR.mkdir(parents=True, exist_ok=True)
            log_file.write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror("C/C++ DevKit", f"The app crashed. Details saved to:\n{log_file}")
        except Exception:  # noqa: BLE001
            print(traceback.format_exc())
        raise
