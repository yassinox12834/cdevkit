"""PATH handling, timeouts, cancel and stopping child processes. Run with:  python -m unittest discover tests"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devkit import configure, system  # noqa: E402

PY = sys.executable


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # A zombie still answers kill(0) until reaped; treat it as gone.
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return True


class PathTests(unittest.TestCase):
    def test_prepend_puts_directory_first(self):
        self.assertEqual(system.prepend_path_entry(r"C:\a;C:\b", r"C:\msys64\ucrt64\bin"),
                         r"C:\msys64\ucrt64\bin;C:\a;C:\b")

    def test_prepend_moves_an_existing_entry_to_the_front(self):
        value = r"C:\old\mingw\bin;C:\msys64\ucrt64\bin\;C:\b"
        self.assertEqual(system.prepend_path_entry(value, r"C:\msys64\ucrt64\bin"),
                         r"C:\msys64\ucrt64\bin;C:\old\mingw\bin;C:\b")

    def test_prepend_is_stable_when_already_first(self):
        value = r"C:\msys64\ucrt64\bin;C:\a"
        self.assertEqual(system.prepend_path_entry(value, r"C:\msys64\ucrt64\bin"), value)

    def test_prepend_on_empty_path(self):
        self.assertEqual(system.prepend_path_entry("", r"C:\x"), r"C:\x")

    def _fake_tool(self, folder: Path, name: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        exe = folder / (name + ".exe" if system.IS_WINDOWS else name)
        exe.write_text("")
        exe.chmod(0o755)

    def test_path_shadow_finds_an_earlier_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, good = Path(tmp) / "old-mingw", Path(tmp) / "ucrt64"
            self._fake_tool(old, "gcc")
            self._fake_tool(good, "gcc")
            self.assertEqual(system.path_shadow("gcc", good, os.pathsep.join([str(old), str(good)])), old)
            self.assertIsNone(system.path_shadow("gcc", good, os.pathsep.join([str(good), str(old)])))

    def test_path_shadow_ignores_missing_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(system.path_shadow("gcc", Path(tmp), tmp))

    def test_path_conflicts_is_windows_only(self):
        if not system.IS_WINDOWS:
            self.assertEqual(system.path_conflicts(), [])


class RunStreamTests(unittest.TestCase):
    def tearDown(self):
        system.reset_cancel()

    def test_output_and_exit_code(self):
        lines = []
        rc = system.run_stream([PY, "-c", "print('a'); print('b'); raise SystemExit(3)"], lines.append, echo=False)
        self.assertEqual(rc, 3)
        self.assertEqual(lines, ["a", "b"])

    def test_carriage_return_progress_keeps_last_frame(self):
        lines = []
        system.run_stream([PY, "-c", "import sys; sys.stdout.write('10%\\r50%\\r100%\\n')"], lines.append, echo=False)
        self.assertEqual(lines, ["100%"])

    def test_missing_command(self):
        lines = []
        self.assertEqual(system.run_stream(["no-such-program-cdevkit"], lines.append, echo=False), 127)
        self.assertIn("not found", lines[-1])

    def test_timeout_stops_a_hung_command(self):
        lines = []
        start = time.perf_counter()
        rc = system.run_stream([PY, "-c", "import time; time.sleep(60)"], lines.append, echo=False, timeout=1)
        self.assertEqual(rc, system.EXIT_TIMEOUT)
        self.assertLess(time.perf_counter() - start, 15)
        self.assertIn("stopped after", lines[-1])

    def test_cancel_stops_a_running_command(self):
        result = {}

        def worker():
            result["rc"] = system.run_stream([PY, "-c", "import time; time.sleep(60)"], lambda _: None, echo=False)
        t = threading.Thread(target=worker)
        start = time.perf_counter()
        t.start()
        time.sleep(0.7)
        system.cancel_running()
        t.join(20)
        self.assertFalse(t.is_alive())
        self.assertEqual(result["rc"], system.EXIT_CANCELLED)
        self.assertLess(time.perf_counter() - start, 15)

    def test_after_cancel_new_commands_refuse_until_reset(self):
        system.cancel_running()
        self.assertTrue(system.cancelled())
        self.assertEqual(system.run_stream([PY, "-c", "pass"], lambda _: None), system.EXIT_CANCELLED)
        system.reset_cancel()
        self.assertEqual(system.run_stream([PY, "-c", "pass"], lambda _: None, echo=False), 0)

    @unittest.skipIf(system.IS_WINDOWS, "uses /proc-style process checks")
    def test_timeout_also_stops_grandchildren(self):
        # Installers start helpers (pkexec -> apt -> dpkg). Killing only the first process
        # would leave the rest running.
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "pid"
            code = ("import subprocess, sys, time;"
                    f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
                    f"open({str(pidfile)!r}, 'w').write(str(p.pid)); time.sleep(60)")
            system.run_stream([PY, "-c", code], lambda _: None, echo=False, timeout=2)
            grandchild = int(pidfile.read_text())
            for _ in range(50):
                if not alive(grandchild):
                    break
                time.sleep(0.1)
            self.assertFalse(alive(grandchild), "grandchild still running")


class CaptureTests(unittest.TestCase):
    def test_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = system.run_capture([PY, "-c", "import os; print(os.getcwd())"], cwd=tmp)
            self.assertEqual(rc, 0)
            self.assertEqual(Path(out.strip()).resolve(), Path(tmp).resolve())

    def test_timeout(self):
        rc, _ = system.run_capture([PY, "-c", "import time; time.sleep(30)"], timeout=0.5)
        self.assertEqual(rc, 1)


class EmailTests(unittest.TestCase):
    def test_valid(self):
        for good in ("me@example.com", "a.b+c@sub.domain.org", "  x@y.io  "):
            self.assertTrue(configure.valid_email(good), good)

    def test_invalid(self):
        for bad in ("", "@", "me@", "@example.com", "me@example", "me @example.com", "a@b@c.com", "me@example."):
            self.assertFalse(configure.valid_email(bad), bad)

    def test_set_identity_refuses_bad_email(self):
        logs = []
        self.assertFalse(configure.set_git_identity("Me", "me@nowhere", logs.append))
        self.assertTrue(any("valid email" in line or "not installed" in line for line in logs))


class SettingsStoreTests(unittest.TestCase):
    def test_round_trip_and_broken_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = system.APP_DIR
            system.APP_DIR = Path(tmp)
            try:
                s = system.Settings("t")
                s.set("x", [1, 2])
                s.save()
                self.assertEqual(system.Settings("t").get("x"), [1, 2])
                (Path(tmp) / "t.json").write_text("{broken")
                self.assertEqual(system.Settings("t").get("x", "default"), "default")
            finally:
                system.APP_DIR = old


if __name__ == "__main__":
    unittest.main()
