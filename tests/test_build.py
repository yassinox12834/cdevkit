"""Rebuild check, dependency parsing and the Windows run script. Run with:  python -m unittest discover tests"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devkit import toolchain  # noqa: E402

HAS_GCC = shutil.which("gcc") is not None and shutil.which("g++") is not None


def touch_later(path: Path, seconds: float = 10) -> None:
    """Make `path` look newer than everything else, without sleeping."""
    t = time.time() + seconds
    os.utime(path, (t, t))


class DepfileTests(unittest.TestCase):
    def test_simple_rule(self):
        self.assertEqual(toolchain.parse_depfile("main.o: main.cpp a.h b.h\n"), ["main.cpp", "a.h", "b.h"])

    def test_continuations_and_escaped_spaces(self):
        text = "main.o: main.cpp inc/a.h \\\n  my\\ dir/b.h \\\r\n  c.h\n"
        self.assertEqual(toolchain.parse_depfile(text), ["main.cpp", "inc/a.h", "my dir/b.h", "c.h"])

    def test_windows_drive_letters_are_not_separators(self):
        text = "util.o: C:\\x\\util.cpp C:\\x\\c.h\n"
        self.assertEqual(toolchain.parse_depfile(text), ["C:\\x\\util.cpp", "C:\\x\\c.h"])

    def test_several_rules_without_duplicates(self):
        text = "a.o: a.cpp common.h\nb.o: b.cpp common.h\n"
        self.assertEqual(toolchain.parse_depfile(text), ["a.cpp", "common.h", "b.cpp"])

    def test_empty_and_phony(self):
        self.assertEqual(toolchain.parse_depfile(""), [])
        self.assertEqual(toolchain.parse_depfile("a.h:\n"), [])


class StampTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "main.cpp"
        self.header = self.dir / "a.h"
        self.src.write_text("int main(){}")
        self.header.write_text("")
        self.out = self.dir / "build" / "main"
        self.out.parent.mkdir()
        self.out.write_text("binary")
        touch_later(self.out, 5)
        self.cmd = ["g++", "-std=c++20", "-O0", str(self.src), "-o", str(self.out)]
        toolchain.write_stamp(self.out, self.cmd, "13.2.0", [str(self.header)])

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, cmd=None, version="13.2.0"):
        return toolchain.needs_build(self.out, cmd or self.cmd, version, [self.src])

    def test_up_to_date(self):
        self.assertEqual(self.check(), (False, "up to date"))

    def test_changed_option_rebuilds(self):
        # The bug this fixes: switching -O0 to -O2 used to run the old executable.
        cmd = [c if c != "-O0" else "-O2" for c in self.cmd]
        self.assertEqual(self.check(cmd), (True, "build options changed"))

    def test_new_compiler_rebuilds(self):
        self.assertEqual(self.check(version="14.1.0"), (True, "compiler changed"))

    def test_changed_header_rebuilds(self):
        touch_later(self.header, 20)
        self.assertEqual(self.check(), (True, "a.h changed"))

    def test_changed_source_rebuilds(self):
        touch_later(self.src, 20)
        self.assertEqual(self.check(), (True, "main.cpp changed"))

    def test_deleted_header_rebuilds(self):
        self.header.unlink()
        self.assertEqual(self.check(), (True, "a.h is gone"))

    def test_missing_or_broken_stamp_rebuilds(self):
        toolchain.stamp_path(self.out).write_text("not json")
        self.assertTrue(self.check()[0])
        toolchain.stamp_path(self.out).unlink()
        self.assertEqual(self.check(), (True, "no record of the last build"))

    def test_missing_executable_rebuilds(self):
        self.out.unlink()
        self.assertEqual(self.check(), (True, "no executable yet"))

    def test_stamp_is_next_to_the_executable(self):
        self.assertEqual(toolchain.stamp_path(self.out), self.out.parent / "main.stamp.json")
        data = json.loads(toolchain.stamp_path(self.out).read_text())
        self.assertEqual(data["command"], self.cmd)


@unittest.skipUnless(HAS_GCC, "gcc not installed")
class RealDependencyTests(unittest.TestCase):
    def test_header_in_include_folder_is_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inc").mkdir()
            header = root / "inc" / "value.h"
            header.write_text("#define VALUE 1\n")
            src = root / "main.c"
            src.write_text('#include <stdio.h>\n#include "value.h"\nint main(void){printf("%d\\n", VALUE);return 0;}\n')
            opts = toolchain.BuildOptions(language="c", standard="c17", extra_flags="-Iinc")
            out = toolchain.output_path(src)
            out.parent.mkdir()
            cmd = toolchain.build_command(toolchain.find_compiler("c"), [src], out, opts)
            self.assertEqual(subprocess.run(cmd, cwd=root, capture_output=True).returncode, 0)

            dep = subprocess.run(toolchain.dependency_command(cmd[0], [src], opts), cwd=root,
                                 capture_output=True, text=True)
            deps = [str((root / d).resolve()) for d in toolchain.parse_depfile(dep.stdout)]
            self.assertIn(str(header.resolve()), deps)
            self.assertFalse(any("stdio.h" in d for d in deps), "system headers must be left out")

            toolchain.write_stamp(out, cmd, "x", deps)
            touch_later(out, 5)
            self.assertFalse(toolchain.needs_build(out, cmd, "x", [src])[0])
            touch_later(header, 20)
            self.assertEqual(toolchain.needs_build(out, cmd, "x", [src]), (True, "value.h changed"))


class WindowsRunScriptTests(unittest.TestCase):
    def test_special_characters_stay_literal(self):
        exe = Path("C:/My Code/build/a.exe")     # str() gives backslashes on Windows, slashes elsewhere
        script = toolchain.windows_run_script(exe, ["x&y", "50%", "a b", "|", ""])
        lines = script.split("\r\n")
        self.assertEqual(lines[0], "@echo off")
        self.assertEqual(lines[1], f'"{exe}" "x&y" "50%%" "a b" "|" ""')
        self.assertIn("echo [exit code %errorlevel%]", lines)
        self.assertIn("pause", lines)
        self.assertTrue(script.endswith("\r\n"))

    def test_embedded_quote_is_escaped(self):
        line = toolchain.windows_run_script(Path("a.exe"), ['say "hi"']).split("\r\n")[1]
        self.assertEqual(line, '"a.exe" "say \\"hi\\""')


if __name__ == "__main__":
    unittest.main()
