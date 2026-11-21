"""Shared look and widgets for both apps, built on Qt (PySide6).

Qt draws natively and has real cross-thread signals, so the interface stays
responsive while installs and builds run in the background.
"""

from __future__ import annotations

import re
import sys
import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from . import system

# ------------------------------------------------------------------ palette
BG = "#0b0d11"
SIDEBAR = "#0f1216"
SURFACE = "#13161c"
SURFACE_2 = "#1a1e26"
BORDER = "#242a34"
TEXT = "#e6e8eb"
MUTED = "#8a919c"
FAINT = "#5c636e"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2f6fde"
OK = "#3fb950"
WARN = "#d29922"
ERR = "#f26a63"

TILE_COLORS = {
    "toolchain": ("#162238", "#8fb4ff"),
    "build": ("#221d36", "#b9a4ff"),
    "editor": ("#13282f", "#7fd0e6"),
    "quality": ("#172b20", "#7fd49a"),
    "github": ("#22242a", "#d6d8dc"),
    "docs": ("#30251a", "#e9b872"),
}

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; }}
QLabel {{ background: transparent; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QWidget#sidebar QLabel {{ background: transparent; }}
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#card QLabel, QFrame#card QCheckBox, QFrame#card QWidget#row {{ background: transparent; }}
QFrame#divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QLabel[role="title"] {{ font-size: 17pt; font-weight: 600; }}
QLabel[role="heading"] {{ font-size: 12pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="faint"] {{ color: {FAINT}; }}
QLabel[role="caps"] {{ color: {MUTED}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[role="badge"] {{ color: {ACCENT}; background: {SURFACE_2}; border-radius: 4px; padding: 2px 6px;
                        font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[role="pill"] {{ background: {SURFACE_2}; border-radius: 6px; padding: 4px 10px; }}

QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px;
               padding: 6px 14px; color: {TEXT}; }}
QPushButton:hover {{ background: #222833; }}
QPushButton:pressed {{ background: #2a313d; }}
QPushButton:disabled {{ color: {FAINT}; background: #14171d; border-color: #1d2129; }}
QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[primary="true"]:disabled {{ background: #1c2d4d; border-color: #1c2d4d; color: #7f95bd; }}
QPushButton[flat="true"] {{ background: transparent; border: none; color: {MUTED}; padding: 2px 8px; }}
QPushButton[flat="true"]:hover {{ color: {TEXT}; }}
QPushButton#nav {{ text-align: left; border: none; background: transparent; color: {MUTED};
                   padding: 9px 12px; border-radius: 6px; }}
QPushButton#nav:hover {{ background: #151920; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SURFACE_2}; color: {TEXT}; }}
QPushButton[seg="true"] {{ border-radius: 0; padding: 5px 12px; margin: 0; }}
QPushButton[seg="true"]:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton[segpos="first"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QPushButton[segpos="last"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}

QLineEdit, QPlainTextEdit, QComboBox {{ background: #161a21; border: 1px solid {BORDER}; border-radius: 6px;
                                        padding: 5px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QPlainTextEdit#console {{ background: {SURFACE}; border: none; padding: 2px 6px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #161a21; border: 1px solid {BORDER}; outline: none;
                               selection-background-color: {ACCENT}; }}

QCheckBox {{ spacing: 9px; background: transparent; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid #3a424e;
                        background: #161a21; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a303b; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4250; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 2px; max-height: 3px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""


def _pick(families: list[str]) -> str | None:
    available = set(QFontDatabase.families())
    return next((f for f in families if f in available), None)


def mono_font(size: int = 10) -> QFont:
    family = _pick(["Cascadia Mono", "Consolas", "JetBrains Mono", "SF Mono", "Menlo", "DejaVu Sans Mono"])
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(size)
    return font


def create_app(title: str) -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(title)
    app.setStyle("Fusion")
    family = _pick(["Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Cantarell"])
    font = QFont(family) if family else app.font()
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLE)
    _install_crash_handler()
    return app


def _install_crash_handler() -> None:
    def handler(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log_file = system.APP_DIR / "crash.log"
        try:
            system.APP_DIR.mkdir(parents=True, exist_ok=True)
            log_file.write_text(text, encoding="utf-8")
        except OSError:
            pass
        print(text, file=sys.stderr)
        QMessageBox.critical(None, "C/C++ DevKit", f"Something went wrong. Details saved to:\n{log_file}")
    sys.excepthook = handler


# ------------------------------------------------------------------ widgets
def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str, on_click=None, primary: bool = False, flat: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        b.setProperty("primary", True)
    if flat:
        b.setProperty("flat", True)
    if on_click:
        b.clicked.connect(lambda _checked=False: on_click())
    return b


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(8)
    return frame, layout


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    return line


def row(*widgets, spacing: int = 8, stretch_end: bool = True) -> QWidget:
    w = QWidget()
    w.setObjectName("row")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for item in widgets:
        if item == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(item)
    if stretch_end:
        lay.addStretch(1)
    return w


class Dot(QLabel):
    COLORS = {"ok": OK, "missing": FAINT, "warn": WARN, "error": ERR, "busy": ACCENT}

    def __init__(self, state: str = "missing"):
        super().__init__("●")
        self.setFixedWidth(14)
        self.set(state)

    def set(self, state: str) -> None:
        self.setStyleSheet(f"color: {self.COLORS.get(state, FAINT)}; background: transparent;")


def tile(letters: str, category: str, size: int = 34) -> QLabel:
    """Square two-letter monogram: a neutral stand-in for each tool's icon."""
    bg, fg = TILE_COLORS.get(category, (SURFACE_2, TEXT))
    lbl = QLabel(letters)
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(f"background: {bg}; color: {fg}; border-radius: 8px; font-weight: 700; font-size: 9pt;")
    return lbl


class Segmented(QWidget):
    """A row of joined toggle buttons, one selected at a time."""

    changed = Signal(str)

    def __init__(self, values: list[str], current: str | None = None):
        super().__init__()
        self.setObjectName("row")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(lambda b: self.changed.emit(b.text()))
        self.set_values(values, current)

    def set_values(self, values: list[str], current: str | None = None) -> None:
        for b in self._group.buttons():
            self._group.removeButton(b)
            b.deleteLater()
        for i, value in enumerate(values):
            b = QPushButton(value)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("seg", True)
            if i == 0:
                b.setProperty("segpos", "first")
            if i == len(values) - 1:
                b.setProperty("segpos", "last")
            self._group.addButton(b)
            self._layout.addWidget(b)
        self.set_value(current if current in values else values[0])

    def value(self) -> str:
        checked = self._group.checkedButton()
        return checked.text() if checked else ""

    def set_value(self, value: str) -> None:
        for b in self._group.buttons():
            if b.text() == value:
                b.setChecked(True)


# ----------------------------------------------------------------- console
_LOCATION = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+)(?::\d+)?:")


class Console(QPlainTextEdit):
    """Read-only, colour-coded output. Double-click an error line to open it in VS Code."""

    COLORS = {"cmd": ACCENT, "err": ERR, "warn": WARN, "ok": OK, "muted": MUTED}

    def __init__(self):
        super().__init__()
        self.setObjectName("console")
        self.setReadOnly(True)
        self.setFont(mono_font())
        self.setMaximumBlockCount(5000)          # old lines are dropped, memory stays flat
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._formats = {}
        for tag, color in self.COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._formats[tag] = fmt
        self._plain = QTextCharFormat()
        self._plain.setForeground(QColor(TEXT))

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

    def _insert(self, text: str, fmt: QTextCharFormat) -> None:
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text, fmt)
        if at_bottom:                             # do not jump if the user scrolled up to read
            bar.setValue(bar.maximum())

    def write(self, line: str, tag: str | None = None) -> None:
        tag = tag or self.classify(line)
        self._insert(line + "\n", self._formats.get(tag, self._plain))

    def write_raw(self, chunk: str) -> None:
        self._insert(chunk, self._plain)

    def mouseDoubleClickEvent(self, event) -> None:
        line = self.cursorForPosition(event.position().toPoint()).block().text().strip()
        m = _LOCATION.match(line)
        if m and system.open_in_vscode(m.group("file"), int(m.group("line"))):
            return
        super().mouseDoubleClickEvent(event)


def console_panel(title: str) -> tuple[QFrame, Console]:
    frame, lay = card()
    lay.setContentsMargins(12, 8, 8, 8)
    lay.setSpacing(4)
    console = Console()
    head = row(label(title.upper(), "caps"), "stretch",
               button("Copy", lambda: QApplication.clipboard().setText(console.toPlainText()), flat=True),
               button("Clear", console.clear, flat=True), stretch_end=False)
    lay.addWidget(head)
    lay.addWidget(console, 1)
    return frame, console


# ------------------------------------------------------------- task runner
class TaskRunner(QObject):
    """Runs one blocking job at a time on a worker thread.

    Workers never touch widgets: they emit signals, and Qt delivers them on the
    UI thread. Jobs started while another is running wait in a queue.
    """

    _log = Signal(str)
    _raw = Signal(str)
    _call = Signal(object)
    _done = Signal(object, object)
    busy_changed = Signal(bool, str)

    def __init__(self, console: Console):
        super().__init__()
        self.console = console
        self.busy = False
        self._pending: list = []
        self._log.connect(console.write)
        self._raw.connect(console.write_raw)
        self._call.connect(lambda fn: fn())
        self._done.connect(self._finish)

    def log(self, line: str) -> None:              # safe from any thread
        self._log.emit(line)

    def raw(self, chunk: str) -> None:              # safe from any thread
        self._raw.emit(chunk)

    def ui(self, fn: Callable[[], None]) -> None:   # run fn on the UI thread
        self._call.emit(fn)

    def run(self, label_text: str, job: Callable[[], object], done: Callable[[object], None] | None = None) -> None:
        if self.busy:
            self._pending.append((label_text, job, done))
            return
        self.busy = True
        self.busy_changed.emit(True, label_text)

        def worker():
            result = None
            try:
                result = job()
            except Exception:  # noqa: BLE001  (show any failure in the console)
                for line in traceback.format_exc().rstrip().splitlines():
                    self.log("error: " + line if line.startswith("Traceback") else line)
            finally:
                self._done.emit(done, result)

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, done, result) -> None:
        self.busy = False
        self.busy_changed.emit(False, "")
        if done:
            done(result)
        if self._pending and not self.busy:
            self.run(*self._pending.pop(0))
