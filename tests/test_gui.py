"""Off-screen tests of the Qt interface. Run with:  python -m unittest discover tests

They need PySide6 (skipped otherwise) but no display: Qt draws into memory.
The flood tests are the regression tests for "the window freezes": they measure the
longest time the UI thread was unable to handle events while output pours in."""

from __future__ import annotations

import gc
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QScrollArea
    HAS_QT = True
except ImportError:            # the toolkit is optional for the logic tests
    HAS_QT = False

from devkit import system, toolchain  # noqa: E402

HAS_GCC = shutil.which("gcc") is not None and shutil.which("g++") is not None
MAX_STALL = 0.5                # seconds the window may stop responding, at most

_tmp_home: tempfile.TemporaryDirectory | None = None
_old_app_dir = system.APP_DIR


def setUpModule():
    global _tmp_home
    _tmp_home = tempfile.TemporaryDirectory()
    system.APP_DIR = Path(_tmp_home.name)      # never touch the real ~/.cdevkit


def tearDownModule():
    system.APP_DIR = _old_app_dir
    if _tmp_home:
        _tmp_home.cleanup()


def app() -> "QApplication":
    from devkit import qt as ui
    return QApplication.instance() or ui.create_app("C/C++ DevKit tests")


class StallMeter:
    """Records the largest gap between ticks of a 10 ms timer on the UI thread."""

    def __init__(self):
        self.worst = 0.0
        self._last = time.perf_counter()
        self._timer = QTimer()
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        now = time.perf_counter()
        self.worst = max(self.worst, now - self._last)
        self._last = now

    def start(self):
        self._last = time.perf_counter()
        self._timer.start()

    def stop(self):
        self._timer.stop()


def wait_until(condition, timeout: float = 60) -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if condition():
            return True
        time.sleep(0.002)
    return False


def collect() -> None:
    """Free dead Qt objects on the UI thread. Left to chance, Python's garbage collector
    may run on a worker thread, and Qt objects with timers must die on their own thread."""
    QApplication.processEvents()
    gc.collect()


def idle(tasks) -> bool:
    return not tasks.busy and not tasks._pending


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class ConsoleTests(unittest.TestCase):
    def setUp(self):
        app()
        from devkit import qt as ui
        self.ui = ui
        self.console = ui.Console()

    def tearDown(self):
        del self.console
        collect()

    def test_batch_keeps_order_and_colours(self):
        self.console.append_batch([("line", "$ gcc a.c"), ("line", "a.c:3:1: error: oops"),
                                   ("raw", "par"), ("raw", "tial\n"), ("line", "✓ done")])
        self.assertEqual(self.console.toPlainText(), "$ gcc a.c\na.c:3:1: error: oops\npartial\n✓ done\n")
        doc = self.console.document()
        err_block = doc.findBlockByNumber(1)
        color = err_block.begin().fragment().charFormat().foreground().color().name()
        self.assertEqual(color, self.ui.ERR)

    def test_line_limit_keeps_memory_flat(self):
        self.console.append_batch([("line", f"l{i}") for i in range(12_000)])
        self.assertLessEqual(self.console.document().blockCount(), 5001)
        self.assertIn("l11999", self.console.toPlainText())

    def test_classify(self):
        c = self.ui.Console.classify
        self.assertEqual(c("$ make"), "cmd")
        self.assertEqual(c("main.c:1: warning: unused"), "warn")
        self.assertEqual(c("undefined reference to `f'"), "err")
        self.assertIsNone(c("hello"))


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        app()
        from devkit import qt as ui
        self.console = ui.Console()
        self.tasks = ui.TaskRunner(self.console)

    def tearDown(self):
        system.reset_cancel()
        wait_until(lambda: idle(self.tasks), 20)
        del self.tasks, self.console
        collect()

    def test_flood_of_lines_does_not_freeze_the_window(self):
        def job():
            for i in range(200_000):
                self.tasks.log(f"line {i} " + "x" * 40)
        meter = StallMeter()
        meter.start()
        self.tasks.run("Flooding...", job)
        self.assertTrue(wait_until(lambda: idle(self.tasks), 120))
        meter.stop()
        text = self.console.toPlainText()
        self.assertIn("line 199999", text)             # the end is always shown
        self.assertLess(meter.worst, MAX_STALL, f"UI thread stalled for {meter.worst:.2f} s")

    def test_skipped_output_is_announced(self):
        self.tasks.MAX_BACKLOG = 1_000
        for i in range(500):
            self.tasks.log(f"line {i}")
        self.tasks.flush(everything=True)
        text = self.console.toPlainText()
        self.assertIn("characters of output skipped", text)
        self.assertIn("line 499", text)
        self.assertNotIn("line 0\n", text)

    def test_output_comes_before_the_done_callback(self):
        seen = []
        self.tasks.run("x", lambda: [self.tasks.log(f"n{i}") for i in range(1000)],
                       lambda _: seen.append(self.console.toPlainText().count("\n")))
        self.assertTrue(wait_until(lambda: idle(self.tasks)))
        self.assertEqual(seen, [1000])

    def test_jobs_queue_and_run_in_order(self):
        order = []
        for i in range(3):
            self.tasks.run(f"job {i}", lambda i=i: order.append(i))
        self.assertTrue(wait_until(lambda: idle(self.tasks)))
        self.assertEqual(order, [0, 1, 2])

    def test_exception_in_job_is_shown_not_raised(self):
        self.tasks.run("boom", lambda: 1 / 0)
        self.assertTrue(wait_until(lambda: idle(self.tasks)))
        self.assertIn("ZeroDivisionError", self.console.toPlainText())

    def test_cancel_stops_the_command_and_the_queue(self):
        ran = []
        self.tasks.run("sleep", lambda: system.run_stream(
            [sys.executable, "-c", "import time; time.sleep(60)"], self.tasks.log, echo=False))
        self.tasks.run("never", lambda: ran.append(1))
        wait_until(lambda: False, 0.7)
        start = time.perf_counter()
        self.tasks.cancel()
        self.assertTrue(wait_until(lambda: idle(self.tasks), 20))
        self.assertLess(time.perf_counter() - start, 15)
        self.assertEqual(ran, [])
        self.assertIn("Cancelled.", self.console.toPlainText())


@unittest.skipUnless(HAS_QT, "PySide6 not installed")
class SetupWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()
        import setup_app
        cls.window = setup_app.SetupWindow()
        cls.window.show()
        wait_until(lambda: idle(cls.window.tasks), 120)

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        cls.window.deleteLater()
        wait_until(lambda: False, 0.1)
        del cls.window
        collect()

    def test_every_offered_component_has_a_row(self):
        expected = {c.key for p in __import__("devkit.packs", fromlist=["PACKS"]).PACKS
                    for c in p.available(system.PLATFORM, self.window.manager)}
        self.assertEqual(set(self.window.rows), expected)

    def test_scrolling_the_pages_stays_responsive(self):
        for key, page in self.window.pages.items():
            self.window.show_page(key)
            area = page.findChild(QScrollArea)
            bar = area.verticalScrollBar()
            meter = StallMeter()
            meter.start()
            for i in range(200):
                bar.setValue(bar.maximum() if i % 2 else bar.minimum())
                QApplication.processEvents()
            meter.stop()
            self.assertLess(meter.worst, MAX_STALL, f"{key}: stalled {meter.worst:.2f} s while scrolling")

    def test_cancel_button_only_while_busy(self):
        self.assertTrue(self.window.b_cancel.isHidden())
        self.window.tasks.run("wait", lambda: time.sleep(0.5))
        self.assertFalse(self.window.b_cancel.isHidden())
        self.assertTrue(wait_until(lambda: idle(self.window.tasks)))
        self.assertTrue(self.window.b_cancel.isHidden())

    def test_failed_install_is_not_configured(self):
        from devkit.packs import ALL_COMPONENTS
        comp = next(ALL_COMPONENTS[k] for k in self.window.rows)
        with mock.patch.object(self.window.installer, "install", return_value=False), \
             mock.patch.object(self.window.installer, "post_configure") as post:
            self.window.install_one(comp)
            self.assertTrue(wait_until(lambda: idle(self.window.tasks), 60))
            post.assert_not_called()
        with mock.patch.object(self.window.installer, "install", return_value=True), \
             mock.patch.object(self.window.installer, "post_configure") as post:
            self.window.install_one(comp)
            self.assertTrue(wait_until(lambda: idle(self.window.tasks), 60))
            post.assert_called_once()

    def test_verify_lists_every_tool(self):
        self.window.check_tools()
        self.assertTrue(wait_until(lambda: idle(self.window.tasks), 120))
        values = [v.text() for _, v in self.window.verify_rows.values()]
        self.assertNotIn("not checked", values)


@unittest.skipUnless(HAS_QT and HAS_GCC, "PySide6 or gcc missing")
class LauncherWindowTests(unittest.TestCase):
    def setUp(self):
        app()
        import launcher_app
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.window = launcher_app.LauncherWindow()
        self.window.show()
        self.assertTrue(wait_until(lambda: idle(self.window.tasks), 60))

    def tearDown(self):
        self.window.stop()
        wait_until(lambda: idle(self.window.tasks), 20)
        self.window.close()
        self.window.deleteLater()                 # destroy now, while Qt is running
        wait_until(lambda: False, 0.1)
        del self.window
        collect()
        self.tmp.cleanup()
        system.reset_cancel()

    def source(self, name: str, code: str) -> Path:
        path = self.dir / name
        path.write_text(code, encoding="utf-8")
        self.window.set_file(path)
        return path

    def run_and_wait(self, timeout: float = 120) -> str:
        self.window.run()
        self.assertTrue(wait_until(lambda: idle(self.window.tasks), timeout))
        return self.window.console.toPlainText()

    def test_builds_and_runs_with_stdin(self):
        self.source("sum.c", '#include <stdio.h>\nint main(void){int a,b;scanf("%d %d",&a,&b);'
                             'printf("sum=%d\\n",a+b);return 0;}\n')
        self.window.stdin_box.setPlainText("4 38")
        out = self.run_and_wait()
        self.assertIn("sum=42", out)
        self.assertIn("exit code 0", out)

    def test_changing_an_option_rebuilds(self):
        self.source("hi.cpp", '#include <cstdio>\nint main(){std::puts("hi");}\n')
        self.assertIn("Built", self.run_and_wait())
        self.assertNotIn("Built", self.run_and_wait())           # nothing changed: no rebuild
        self.window.opt.set_value("-O2")
        out = self.run_and_wait()
        self.assertIn("Rebuilding: build options changed", out)
        self.assertIn("-O2", toolchain.stamp_path(toolchain.output_path(self.dir / "hi.cpp")).read_text())

    def test_changing_a_header_rebuilds(self):
        (self.dir / "v.h").write_text("#define V 1\n")
        self.source("v.c", '#include <stdio.h>\n#include "v.h"\nint main(void){printf("v=%d\\n",V);return 0;}\n')
        self.assertIn("v=1", self.run_and_wait())
        (self.dir / "v.h").write_text("#define V 2\n")
        t = time.time() + 10
        os.utime(self.dir / "v.h", (t, t))
        out = self.run_and_wait()
        self.assertIn("v.h changed", out)
        self.assertIn("v=2", out)

    def test_program_flooding_output_does_not_freeze_the_window(self):
        self.source("spam.c", '#include <stdio.h>\nint main(void){for(int i=0;i<300000;i++)'
                              'printf("spam line %d\\n",i);puts("THE END");return 0;}\n')
        self.window.build()
        self.assertTrue(wait_until(lambda: idle(self.window.tasks), 120))
        meter = StallMeter()
        meter.start()
        out = self.run_and_wait()
        meter.stop()
        self.assertIn("THE END", out)
        self.assertLess(meter.worst, MAX_STALL, f"UI thread stalled for {meter.worst:.2f} s")

    def test_stop_ends_a_program_that_never_finishes(self):
        self.source("loop.c", "#include <stdio.h>\nint main(void){puts(\"started\");fflush(stdout);"
                              "for(;;){}return 0;}\n")
        self.window.run()
        self.assertTrue(wait_until(lambda: "started" in self.window.console.toPlainText(), 60))
        self.assertTrue(self.window.b_stop.isEnabled())
        self.window.stop()
        self.assertTrue(wait_until(lambda: idle(self.window.tasks), 20))
        self.assertIn("Stopped by you.", self.window.console.toPlainText())
        self.assertFalse(self.window.b_stop.isEnabled())

    def test_relative_path_still_builds(self):
        (self.dir / "rel.c").write_text('#include <stdio.h>\nint main(void){puts("relative ok");return 0;}\n')
        old = os.getcwd()
        os.chdir(self.dir.parent)
        try:
            self.window.set_file(Path(self.dir.name) / "rel.c")
        finally:
            os.chdir(old)
        self.assertTrue(self.window.file.is_absolute())
        self.assertIn("relative ok", self.run_and_wait())

    def test_preview_follows_the_options(self):
        self.source("p.cpp", "int main(){}\n")
        self.window.checks["werror"].setChecked(True)
        self.window.extra.setText("-DLOCAL")
        preview = self.window.preview.text()
        self.assertIn("-Werror", preview)
        self.assertIn("-DLOCAL", preview)
        self.assertIn("p.cpp", preview)


if __name__ == "__main__":
    unittest.main()
