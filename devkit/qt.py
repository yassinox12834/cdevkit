"""Shared look and widgets for both apps, built on Qt (PySide6).

Qt draws natively and has real cross-thread signals, so the interface stays
responsive while installs and builds run in the background.
"""

from __future__ import annotations

import re
import sys
from collections import deque
import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
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

QSpinBox {{ background: #161a21; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 6px; }}
QSpinBox:focus {{ border-color: {ACCENT}; }}
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

QTreeWidget#explorer {{ background: transparent; border: none; outline: none; show-decoration-selected: 0; }}
QTreeWidget#explorer::item {{ padding: 3px 2px; border-radius: 4px; }}
QTreeWidget#explorer::item:hover {{ background: #1a1f28; }}
QTreeWidget#explorer::item:selected {{ background: #1d2a40; color: {TEXT}; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

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
        if QApplication.instance():
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


# Explorer icons, in the spirit of VS Code's file icons: (badge text, colour).
FILE_BADGES = {
    "c": ("C", "#5c9ce6"),
    "cpp": ("C++", "#a77bf0"),
    "header": ("H", "#c08ee8"),
}
_icons: dict[tuple[str, bool], QIcon] = {}


def file_icon(kind: str, runnable: bool = False) -> QIcon:
    """Icon for an explorer row: a coloured badge for C, C++ and headers, a folder or a
    plain page otherwise. Files that define main() get a green dot in the corner."""
    key = (kind, runnable)
    if key in _icons:
        return _icons[key]
    scale = 2                                         # drawn at 2x so it stays sharp on HiDPI screens
    size = 18
    pix = QPixmap(size * scale, size * scale)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.scale(scale, scale)
    if kind == "dir":
        path = QPainterPath()
        path.moveTo(1.5, 4.5)
        path.lineTo(7, 4.5)
        path.lineTo(8.5, 6)
        path.lineTo(16.5, 6)
        path.lineTo(16.5, 15)
        path.lineTo(1.5, 15)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#c9a25a"))
        p.drawPath(path)
    elif kind in FILE_BADGES:
        text, color = FILE_BADGES[kind]
        font = QFont()
        font.setBold(True)
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor(color))
        if text == "C++":                             # a big C with a small ++ above, as VS Code draws it
            p.drawText(QRectF(-2, 1, 13, size), Qt.AlignmentFlag.AlignCenter, "C")
            font.setPixelSize(8)
            p.setFont(font)
            p.drawText(QRectF(9, 0, 9, 10), Qt.AlignmentFlag.AlignCenter, "++")
        else:
            p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    else:
        p.setPen(QPen(QColor(FAINT), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(4, 2, 10, 14), 1.5, 1.5)
        for y in (6.5, 9.5, 12.5):
            p.drawLine(6.5, y, 11.5, y)
    if runnable:
        p.setPen(QPen(QColor(BG), 1.5))
        p.setBrush(QColor(OK))
        p.drawEllipse(QRectF(10.5, 10.5, 7.5, 7.5))
    p.end()
    icon = QIcon(pix)
    _icons[key] = icon
    return icon


class ComboBox(QComboBox):
    """A combo box that only reacts to the mouse wheel once it has been clicked.

    Plain Qt combo boxes change value when the wheel passes over them, so scrolling
    the options panel silently switched the C++ standard. Now the wheel scrolls the panel."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()                            # passes the wheel on to the scroll area


class SpinBox(QSpinBox):
    """Same wheel rule as ComboBox."""

    def __init__(self, *args):
        super().__init__(*args)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def smooth_scroll(view: QAbstractItemView) -> None:
    """Scroll lists and trees by pixels rather than by whole rows."""
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    view.verticalScrollBar().setSingleStep(12)


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

    def format_for(self, line: str) -> QTextCharFormat:
        return self._formats.get(self.classify(line), self._plain)

    def append_batch(self, items: list[tuple[str, str]]) -> None:
        """Insert many ("line" | "raw", text) items in one edit, so the widget redraws once.

        Neighbours with the same colour are joined first: a program printing
        10 000 lines becomes a handful of insertions, not 10 000."""
        runs: list[tuple[str, QTextCharFormat]] = []
        for kind, text in items:
            fmt = self.format_for(text) if kind == "line" else self._plain
            text = text + "\n" if kind == "line" else text
            if runs and runs[-1][1] is fmt:
                runs[-1] = (runs[-1][0] + text, fmt)
            else:
                runs.append((text, fmt))
        if not runs:
            return
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        for text, fmt in runs:
            cursor.insertText(text, fmt)
        cursor.endEditBlock()
        if at_bottom:                             # do not jump if the user scrolled up to read
            bar.setValue(bar.maximum())

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
_TEXT = ("line", "raw")


class TaskRunner(QObject):
    """Runs one blocking job at a time on a worker thread.

    Workers never touch widgets and never emit Qt signals. Everything they send
    (output lines, "run this on the UI thread", "the job is done") goes into one
    queue, and a timer on the UI thread empties it every FLUSH_MS, in order:

    * a program printing in a tight loop cannot flood the event loop, so the
      window keeps scrolling and responding;
    * the done callback always comes after the job's last line;
    * no Python object crosses threads through a Qt signal. PySide6 6.12.0 has a
      bug where emitting Signal(object) corrupts memory and crashes the app.

    If output arrives faster than it can be shown, the oldest waiting part is
    dropped and a note says so. Jobs started while another runs wait their turn.
    """

    busy_changed = Signal(bool, str)

    FLUSH_MS = 40               # about 25 redraws a second
    MAX_PER_FLUSH = 60_000      # characters drawn per tick: each tick stays well under 50 ms
    MAX_BACKLOG = 300_000       # characters allowed to wait; older output is dropped

    def __init__(self, console: Console):
        super().__init__(console)                 # destroyed with its console, never after it
        self.console = console
        self.busy = False
        self._pending: list = []
        self._lock = threading.Lock()
        self._queue: deque[tuple[str, object]] = deque()
        self._size = 0                            # characters of text waiting in the queue
        self._dropped = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self.FLUSH_MS)
        self._timer.timeout.connect(self.flush)
        self._timer.start()

    # ------------------------------------------------ from any thread
    def _push(self, kind: str, payload) -> None:
        with self._lock:
            self._queue.append((kind, payload))
            if kind not in _TEXT:
                return
            self._size += len(payload) + 1
            while self._size > self.MAX_BACKLOG:
                # Drop the oldest text, never a call or a done marker.
                for i, (k, old) in enumerate(self._queue):
                    if k in _TEXT and i < len(self._queue) - 1:
                        del self._queue[i]
                        self._size -= len(old) + 1
                        self._dropped += len(old) + 1
                        break
                else:
                    break

    def log(self, line: str) -> None:
        self._push("line", line)

    def raw(self, chunk: str) -> None:
        self._push("raw", chunk)

    def ui(self, fn: Callable[[], None]) -> None:
        """Run fn on the UI thread, after the output sent before it."""
        self._push("call", fn)

    # ------------------------------------------------ UI thread only
    def run(self, label_text: str, job: Callable[[], object], done: Callable[[object], None] | None = None) -> None:
        if self.busy:
            self._pending.append((label_text, job, done))
            return
        self.busy = True
        self.busy_changed.emit(True, label_text)

        def worker():
            result = None
            system.reset_cancel()
            try:
                result = job()
            except Exception:  # noqa: BLE001  (show any failure in the console)
                for line in traceback.format_exc().rstrip().splitlines():
                    self.log("error: " + line if line.startswith("Traceback") else line)
            finally:
                self._push("done", (done, result))

        threading.Thread(target=worker, daemon=True).start()

    def flush(self, everything: bool = False) -> None:
        """Handle what the workers queued: draw a slice of output, run calls in order."""
        while True:
            batch: list[tuple[str, str]] = []
            event = None
            with self._lock:
                size = 0
                while self._queue and (everything or size < self.MAX_PER_FLUSH):
                    kind, payload = self._queue[0]
                    if kind not in _TEXT:
                        event = self._queue.popleft()
                        break
                    self._queue.popleft()
                    batch.append((kind, payload))
                    size += len(payload) + 1
                self._size -= size
                dropped, self._dropped = self._dropped, 0
            if dropped:
                batch.insert(0, ("line", f"[... {dropped:,} characters of output skipped: it came faster "
                                         "than the window can show it ...]"))
            if batch:
                self.console.append_batch(batch)
            if event is None:
                return
            kind, payload = event
            if kind == "call":
                try:
                    payload()
                except Exception:  # noqa: BLE001
                    self.console.write("error: " + traceback.format_exc().rstrip().splitlines()[-1])
            else:
                self._complete(*payload)
            if not everything and size >= self.MAX_PER_FLUSH:
                return                            # the rest waits for the next tick

    def _complete(self, done, result) -> None:
        self.busy = False
        self.busy_changed.emit(False, "")
        if done:
            done(result)
        if self._pending and not self.busy:
            self.run(*self._pending.pop(0))

    def cancel(self) -> None:
        """Stop the running job's commands and forget queued jobs."""
        self._pending.clear()
        if self.busy:
            self.log("Cancelling...")
            system.cancel_running()
