"""Installer logic (with the package managers replaced by fakes), VS Code settings,
the project template and the repository's own files. Run with:  python -m unittest discover tests"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from devkit import installer as inst_mod, project_template, system, vscode_settings  # noqa: E402
from devkit.installer import LINUX_INSTALL, Installer  # noqa: E402
from devkit.packs import ALL_COMPONENTS, PACKS  # noqa: E402


class LinuxCommandTests(unittest.TestCase):
    def test_pacman_never_does_a_partial_upgrade(self):
        cmd = LINUX_INSTALL["pacman"]
        self.assertIn("-Syu", cmd)
        self.assertNotRegex(cmd, r"-Sy\b(?!u)")

    def test_every_manager_has_a_query_command(self):
        self.assertEqual(set(inst_mod.LINUX_QUERY), set(LINUX_INSTALL))


class FakeLinuxInstaller(Installer):
    """Installer on a pretend apt system: records root commands instead of running them."""

    def __init__(self, known: set[str], root_ok: bool = True):
        self.logs: list[str] = []
        super().__init__(self.logs.append, platform="linux", manager="apt")
        self.known = known
        self.root_ok = root_ok
        self.root_calls: list[str] = []
        self.installed: set[str] = set()

    def _as_root(self, script: str) -> int:
        self.root_calls.append(script)
        if self.root_ok:
            self.installed |= {p.strip("'") for p in script.split() if p.strip("'") in self.known}
            return 0
        return 100

    def _installed_set(self, kind: str) -> set[str]:
        return set(self.installed) if kind == "linux" else set()

    def missing_from_repositories(self, packages):
        return [p for p in packages if p not in self.known]


class LinuxBatchTests(unittest.TestCase):
    def setUp(self):
        self.comps = [ALL_COMPONENTS[k] for k in ("gcc", "gdb", "cmake", "make")]
        self.all_pkgs = {p for c in self.comps for p in c.apt}

    def test_one_password_prompt_for_everything(self):
        fake = FakeLinuxInstaller(known=self.all_pkgs)
        done, failed = fake.install_many(self.comps)
        self.assertEqual((done, failed), (4, 0))
        self.assertEqual(len(fake.root_calls), 1)

    def test_unknown_package_is_skipped_not_fatal(self):
        fake = FakeLinuxInstaller(known=self.all_pkgs - {"gdb"})
        done, failed = fake.install_many(self.comps)
        self.assertEqual(len(fake.root_calls), 1)
        self.assertNotIn("gdb", fake.root_calls[0].split())
        self.assertEqual((done, failed), (3, 1))
        self.assertTrue(any("skipped: gdb" in line for line in fake.logs))

    def test_failed_batch_does_not_ask_again_for_each_item(self):
        # The bug: one failure used to open a new password dialog per component.
        fake = FakeLinuxInstaller(known=self.all_pkgs, root_ok=False)
        done, failed = fake.install_many(self.comps)
        self.assertEqual(len(fake.root_calls), 1)
        self.assertEqual((done, failed), (0, 4))

    def test_single_install_after_a_batch_still_works(self):
        fake = FakeLinuxInstaller(known=self.all_pkgs | {"cppcheck"})
        fake.install_many(self.comps)
        self.assertTrue(fake.install(ALL_COMPONENTS["cppcheck"]))
        self.assertEqual(len(fake.root_calls), 2)

    def test_missing_from_repositories_uses_the_query_command(self):
        real = Installer(lambda _: None, platform="linux", manager="apt")
        with mock.patch.object(inst_mod.shutil, "which", return_value="/usr/bin/apt-cache"), \
             mock.patch.object(system, "run_capture",
                               side_effect=lambda cmd, timeout=20: (0 if cmd[-1] == "gcc" else 100, "")) as rc:
            self.assertEqual(real.missing_from_repositories(["gcc", "nope"]), ["nope"])
            self.assertEqual(rc.call_args_list[0].args[0][:2], ["apt-cache", "show"])


class CancelTests(unittest.TestCase):
    def tearDown(self):
        system.reset_cancel()

    def test_install_many_stops_when_cancelled(self):
        fake = FakeLinuxInstaller(known=set())
        system.cancel_running()
        done, failed = fake.install_many([ALL_COMPONENTS["ext-cpptools"], ALL_COMPONENTS["ext-cmake"]])
        self.assertEqual(done, 0)
        self.assertTrue(any("cancelled" in line.lower() for line in fake.logs))


class VSCodeSettingsTests(unittest.TestCase):
    def test_no_editor_habits_in_global_settings(self):
        new = vscode_settings.toolchain_settings(use_clangd=False)
        for key in ("[c]", "[cpp]", "files.trimTrailingWhitespace", "files.insertFinalNewline"):
            self.assertNotIn(key, new)
        self.assertIn("C_Cpp.default.compilerPath", new)

    def test_clangd_settings(self):
        new = vscode_settings.toolchain_settings(use_clangd=True)
        self.assertEqual(new["C_Cpp.intelliSenseEngine"], "disabled")
        self.assertTrue(any(a.startswith("--query-driver=") for a in new["clangd.arguments"]))

    def _apply(self, folder: Path, logs: list[str]) -> bool:
        with mock.patch.object(vscode_settings, "user_settings_path", return_value=folder / "settings.json"):
            return vscode_settings.apply_toolchain_settings(logs.append)

    def test_backups_are_dated_and_never_overwrite_the_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "settings.json").write_text('{"editor.fontSize": 15}')
            logs: list[str] = []
            self.assertTrue(self._apply(folder, logs))
            backups = list(folder.glob("settings.json.*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text()), {"editor.fontSize": 15})
            self.assertRegex(backups[0].name, r"settings\.json\.\d{8}-\d{6}(-\d+)?\.bak")
            merged = json.loads((folder / "settings.json").read_text())
            self.assertEqual(merged["editor.fontSize"], 15)

            # A second change makes a second backup; the first (the original) is still there.
            (folder / "settings.json").write_text('{"editor.fontSize": 16}')
            self._apply(folder, logs)
            self.assertEqual(len(list(folder.glob("settings.json.*.bak"))), 2)
            self.assertIn(backups[0], list(folder.glob("settings.json.*.bak")))

    def test_only_the_newest_backups_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            for i in range(vscode_settings.KEEP_BACKUPS + 3):
                vscode_settings.backup_settings(path, f"{{\"n\": {i}}}")
                time.sleep(0.01)
            kept = sorted(Path(tmp).glob("settings.json.*.bak"), key=lambda p: p.stat().st_mtime)
            self.assertEqual(len(kept), vscode_settings.KEEP_BACKUPS)
            self.assertEqual(json.loads(kept[-1].read_text())["n"], vscode_settings.KEEP_BACKUPS + 2)

    def test_settings_with_comments_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            original = '{\n  // my comment\n  "a": 1\n}'
            (folder / "settings.json").write_text(original)
            logs: list[str] = []
            self.assertFalse(self._apply(folder, logs))
            self.assertEqual((folder / "settings.json").read_text(), original)
            self.assertEqual(list(folder.glob("*.bak")), [])

    def test_nothing_to_do_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            logs: list[str] = []
            self._apply(folder, logs)
            self._apply(folder, logs)
            self.assertIn("already configured", logs[-1])
            self.assertEqual(list(folder.glob("*.bak")), [])


class TemplateExtraTests(unittest.TestCase):
    def test_clangd_points_at_the_preset_build_folder(self):
        files = project_template.render("demo", "cpp", "c++20")
        self.assertIn(".clangd", files)
        self.assertIn("CompilationDatabase: build/debug", files[".clangd"])
        presets = json.loads(files["CMakePresets.json"])
        base = next(p for p in presets["configurePresets"] if p["name"] == "base")
        self.assertEqual(base["binaryDir"], "${sourceDir}/build/${presetName}")

    def test_editor_habits_live_in_the_project(self):
        settings = json.loads(project_template.render("demo", "c", "c17")[".vscode/settings.json"])
        self.assertTrue(settings["[c]"]["editor.formatOnSave"])
        self.assertTrue(settings["files.insertFinalNewline"])

    def test_refuses_a_non_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "demo").mkdir()
            (Path(tmp) / "demo" / "keep.txt").write_text("mine")
            logs: list[str] = []
            self.assertIsNone(project_template.create_project(Path(tmp), "demo", "c", "c17", logs.append,
                                                              git_init=False))
            self.assertEqual((Path(tmp) / "demo" / "keep.txt").read_text(), "mine")

    def test_safe_name(self):
        self.assertEqual(project_template.safe_name("  my app!  "), "my_app")
        self.assertEqual(project_template.safe_name("***"), "app")


class RepositoryFileTests(unittest.TestCase):
    """The start scripts and config files, checked as text."""

    def test_uv_is_pinned_with_a_checksum_for_every_target(self):
        sh = (ROOT / "_common.sh").read_text()
        bat = (ROOT / "_common.bat").read_text()
        self.assertNotIn("releases/latest", sh + bat)
        version_sh = re.search(r'UV_VERSION="([\d.]+)"', sh).group(1)
        version_bat = re.search(r'set "UV_VERSION=([\d.]+)"', bat).group(1)
        self.assertEqual(version_sh, version_bat)
        for target in ("x86_64-apple-darwin", "aarch64-apple-darwin",
                       "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu"):
            self.assertRegex(sh, rf"uv-{target}\)\s+echo [0-9a-f]{{64}}")
        self.assertEqual(len(re.findall(r"UV_SHA=[0-9a-f]{64}", bat)), 2)
        self.assertIn("Get-FileHash", bat)

    def test_scripts_check_for_qt_not_customtkinter(self):
        for name in ("_common.sh", "_common.bat", "requirements.txt"):
            text = (ROOT / name).read_text()
            self.assertNotIn("customtkinter", text.lower(), name)
        self.assertIn("PySide6", (ROOT / "requirements.txt").read_text())

    def test_line_endings_are_normalised(self):
        self.assertRegex((ROOT / ".gitattributes").read_text(), r"(?m)^\* text=auto$")
        self.assertTrue((ROOT / ".gitignore").read_text().endswith("\n"))

    def test_version_is_defined_once(self):
        from devkit import __version__
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_every_pack_has_items_on_every_platform(self):
        for platform, manager in (("windows", None), ("macos", None), ("linux", "apt"),
                                  ("linux", "dnf"), ("linux", "pacman")):
            for pack in PACKS:
                self.assertTrue(pack.available(platform, manager), f"{pack.key} empty on {platform}/{manager}")


if __name__ == "__main__":
    unittest.main()
