"""Tests for the non-GUI logic. Run with:  python -m unittest discover tests"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devkit import project_template, toolchain  # noqa: E402
from devkit.packs import ALL_COMPONENTS, PACKS, install_order  # noqa: E402
from devkit.vscode_settings import merge_settings, toolchain_settings  # noqa: E402

HAS_GCC = shutil.which("gcc") is not None and shutil.which("g++") is not None


class ToolchainTests(unittest.TestCase):
    def test_detect_language(self):
        self.assertEqual(toolchain.detect_language("a.c"), "c")
        self.assertEqual(toolchain.detect_language("a.CPP"), "cpp")
        self.assertEqual(toolchain.detect_language("a.cc"), "cpp")
        self.assertIsNone(toolchain.detect_language("a.py"))

    def test_std_flag(self):
        o = toolchain.BuildOptions(language="c", standard="c99")
        self.assertEqual(toolchain.std_flag(o), "-std=c99")
        o.gnu = True
        self.assertEqual(toolchain.std_flag(o), "-std=gnu99")
        o = toolchain.BuildOptions(language="cpp", standard="c++23", gnu=True)
        self.assertEqual(toolchain.std_flag(o), "-std=gnu++23")

    def test_invalid_standard_falls_back(self):
        o = toolchain.BuildOptions(language="c", standard="c++20")
        self.assertEqual(toolchain.std_flag(o), "-std=c17")

    def test_build_command_flags(self):
        o = toolchain.BuildOptions(language="cpp", standard="c++17", optimisation="-O2", werror=True,
                                   ub_trap=True, static=True, extra_flags="-DX=1 -Iinc")
        cmd = toolchain.build_command("g++", [Path("m.cpp")], Path("out"), o)
        for flag in ("-std=c++17", "-O2", "-g", "-Wall", "-Werror", "-fsanitize=undefined", "-static",
                     "-DX=1", "-Iinc", "m.cpp"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("-o") + 1], "out")

    def test_draft_names_for_old_gcc(self):
        o = toolchain.BuildOptions(language="c", standard="c23", gcc_major=13)
        self.assertEqual(toolchain.std_flag(o), "-std=c2x")
        o.gcc_major = 15
        self.assertEqual(toolchain.std_flag(o), "-std=c23")

    def test_describe_exit(self):
        self.assertIn("access violation", toolchain.describe_exit(-1073741819))  # 0xC0000005 signed
        self.assertIn("stack overflow", toolchain.describe_exit(0xC00000FD))
        self.assertEqual(toolchain.describe_exit(3), "exit code 3")

    def test_collect_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("main.cpp", "util.cpp", "notes.txt", "helper.c"):
                (Path(tmp) / name).write_text("")
            main = Path(tmp) / "main.cpp"
            self.assertEqual(toolchain.collect_sources(main, False), [main])
            names = [p.name for p in toolchain.collect_sources(main, True)]
            self.assertEqual(names, ["main.cpp", "util.cpp"])

    @unittest.skipUnless(HAS_GCC, "gcc not installed")
    def test_every_standard_compiles(self):
        progs = {"c": "#include <stdio.h>\nint main(void){puts(\"ok\");return 0;}\n",
                 "cpp": "#include <cstdio>\nint main(){std::puts(\"ok\");}\n"}
        major = toolchain.gcc_major(toolchain.compiler_version("cpp"))
        with tempfile.TemporaryDirectory() as tmp:
            for lang, code in progs.items():
                src = Path(tmp) / ("t.c" if lang == "c" else "t.cpp")
                src.write_text(code)
                for std in toolchain.supported_standards(lang, major):
                    o = toolchain.BuildOptions(language=lang, standard=std, warnings=False, gcc_major=major)
                    out = Path(tmp) / f"t_{lang}_{std.replace('+', 'p')}"
                    cmd = toolchain.build_command(toolchain.find_compiler(lang), [src], out, o)
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0, f"{std}: {res.stderr}")
                    self.assertEqual(subprocess.run([out], capture_output=True, text=True).stdout.strip(), "ok")

    @unittest.skipUnless(HAS_GCC, "gcc not installed")
    def test_ub_trap_stops_program(self):
        code = "#include <climits>\n#include <cstdio>\nint main(int c, char**){int x = INT_MAX; x += c; std::printf(\"%d\\n\", x);}\n"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "ub.cpp"
            src.write_text(code)
            out = Path(tmp) / "ub"
            o = toolchain.BuildOptions(language="cpp", standard="c++20", ub_trap=True)
            subprocess.run(toolchain.build_command(toolchain.find_compiler("cpp"), [src], out, o), check=True)
            self.assertNotEqual(subprocess.run([out]).returncode, 0)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# file -> minimum standard
EXAMPLE_STANDARDS = {
    "c/01_hello.c": "c89", "c/02_input_sum.c": "c99", "c/03_pointers_structs.c": "c99",
    "c/04_crash_demo.c": "c99", "c/05_image_gradient.c": "c99", "c/06_image_sierpinski.c": "c99",
    "cpp/01_hello.cpp": "c++98", "cpp/02_vectors_algorithms.cpp": "c++11", "cpp/03_classes.cpp": "c++11",
    "cpp/04_cpp20_features.cpp": "c++20", "cpp/05_cpp23_expected.cpp": "c++23",
    "cpp/06_image_mandelbrot.cpp": "c++17", "cpp/07_image_shapes.cpp": "c++17",
}
# file -> minimum GCC major, when the library needs more than the -std flag does.
# GCC 11 accepts -std=c++23 but its library has no <expected> yet.
EXAMPLE_MIN_GCC = {"cpp/05_cpp23_expected.cpp": 12}


class ExampleTests(unittest.TestCase):
    def test_every_example_is_listed(self):
        found = {str(p.relative_to(EXAMPLES)).replace("\\", "/") for p in EXAMPLES.rglob("*.c*")}
        self.assertEqual(found, set(EXAMPLE_STANDARDS))

    @unittest.skipUnless(HAS_GCC, "gcc not installed")
    def test_examples_compile_without_warnings(self):
        major = toolchain.gcc_major(toolchain.compiler_version("cpp"))
        with tempfile.TemporaryDirectory() as tmp:
            for rel, std in EXAMPLE_STANDARDS.items():
                lang = toolchain.detect_language(rel)
                if std not in toolchain.supported_standards(lang, major):
                    continue
                if major and major < EXAMPLE_MIN_GCC.get(rel, 0):
                    continue
                o = toolchain.BuildOptions(language=lang, standard=std, werror=True, gcc_major=major)
                out = Path(tmp) / Path(rel).stem
                cmd = toolchain.build_command(toolchain.find_compiler(lang), [EXAMPLES / rel], out, o)
                res = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"{rel}: {res.stdout}{res.stderr}")

    @unittest.skipUnless(HAS_GCC, "gcc not installed")
    def test_image_example_writes_valid_bmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "shapes"
            o = toolchain.BuildOptions(language="cpp", standard="c++17", optimisation="-O2")
            cmd = toolchain.build_command(toolchain.find_compiler("cpp"), [EXAMPLES / "cpp/07_image_shapes.cpp"], out, o)
            subprocess.run(cmd, check=True)
            subprocess.run([out], cwd=tmp, check=True, capture_output=True)
            data = (Path(tmp) / "shapes.bmp").read_bytes()
            self.assertEqual(data[:2], b"BM")
            self.assertEqual(int.from_bytes(data[2:6], "little"), len(data))
            self.assertEqual(int.from_bytes(data[18:22], "little"), 640)


class PackTests(unittest.TestCase):
    PLATFORMS = [("windows", None), ("macos", None), ("linux", "apt"), ("linux", "dnf"), ("linux", "pacman")]

    def test_keys_unique_and_requirements_exist(self):
        keys = [c.key for p in PACKS for c in p.components]
        self.assertEqual(len(keys), len(set(keys)))
        for comp in ALL_COMPONENTS.values():
            for req in comp.requires:
                self.assertIn(req, ALL_COMPONENTS)
            src = comp.source("windows")
            if src and src[0] in ("winget",):
                self.assertTrue(comp.probe, comp.key)

    def test_every_platform_gets_a_full_classic_pack(self):
        classic = PACKS[0]
        for platform, manager in self.PLATFORMS:
            keys = {c.key for c in classic.available(platform, manager)}
            for needed in ("gcc", "cmake", "git", "vscode", "ext-cpptools"):
                self.assertIn(needed, keys, f"{platform}/{manager}")
        self.assertIn("msys2", {c.key for c in classic.available("windows", None)})
        self.assertIn("homebrew", {c.key for c in classic.available("macos", None)})
        self.assertNotIn("gdb", {c.key for c in classic.available("macos", None)})  # LLDB there
        self.assertNotIn("ext-codelldb", {c.key for c in classic.available("linux", "apt")})

    def test_github_cli_is_in_extras_everywhere(self):
        extras = next(p for p in PACKS if p.key == "extras")
        for platform, manager in self.PLATFORMS:
            self.assertIn("gh", {c.key for c in extras.available(platform, manager)})

    def test_unknown_linux_distribution_only_offers_extensions_and_scripts(self):
        methods = {c.source("linux", None)[0] for c in ALL_COMPONENTS.values() if c.source("linux", None)}
        self.assertLessEqual(methods, {"vscode", "script"})

    def test_order_puts_programs_first(self):
        for platform, manager in self.PLATFORMS:
            comps = [c for c in ALL_COMPONENTS.values() if c.source(platform, manager)]
            ordered = install_order(comps, platform, manager)
            self.assertEqual(ordered[-1].source(platform, manager)[0], "vscode")
            self.assertNotEqual(ordered[0].source(platform, manager)[0], "vscode")


class MacCompilerTests(unittest.TestCase):
    def test_picks_highest_versioned_gcc(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("g++", "g++-13", "g++-15", "g++-15-extra", "gcc-15"):
                (Path(tmp) / name).write_text("")
            self.assertEqual(Path(toolchain._versioned_gcc("g++", [Path(tmp)])).name, "g++-15")
            self.assertIsNone(toolchain._versioned_gcc("gfortran", [Path(tmp)]))


class InstallerTests(unittest.TestCase):
    def test_hidden_component_is_refused(self):
        from devkit.installer import Installer
        logs = []
        inst = Installer(logs.append, platform="linux", manager="apt")
        self.assertFalse(inst.install(ALL_COMPONENTS["msys2"]))
        self.assertIn("not offered", logs[-1])


class SettingsTests(unittest.TestCase):
    def test_merge_keeps_user_values(self):
        existing = {"[cpp]": {"editor.formatOnSave": False}, "editor.fontSize": 15}
        new = toolchain_settings(use_clangd=True)
        merged, changed, kept = merge_settings(existing, new, force={"clangd.path"})
        self.assertEqual(merged["editor.fontSize"], 15)
        self.assertFalse(merged["[cpp]"]["editor.formatOnSave"])
        self.assertIn("[cpp]", kept)
        self.assertIn("clangd.path", changed)
        _, changed_again, _ = merge_settings(merged, new, force={"clangd.path"})
        self.assertEqual(changed_again, [])


class TemplateTests(unittest.TestCase):
    def test_render_is_valid(self):
        files = project_template.render("my app!", "cpp", "c++23")
        self.assertIn("project(my_app LANGUAGES CXX)", files["CMakeLists.txt"])
        self.assertIn("CMAKE_CXX_STANDARD 23", files["CMakeLists.txt"])
        for name in ("CMakePresets.json", ".vscode/tasks.json", ".vscode/launch.json"):
            json.loads(files[name])
        c = project_template.render("x", "c", "c89")
        self.assertIn("CMAKE_C_STANDARD 90", c["CMakeLists.txt"])
        self.assertIn("src/main.c", c)

    @unittest.skipUnless(HAS_GCC and shutil.which("cmake") and shutil.which("ninja"), "cmake/ninja missing")
    def test_generated_project_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = project_template.create_project(Path(tmp), "demo", "cpp", "c++20", lambda _: None, git_init=False)
            for args in (["cmake", "--preset", "debug"], ["cmake", "--build", "--preset", "debug"]):
                res = subprocess.run(args, cwd=dest, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            out = subprocess.run([dest / "build" / "debug" / "demo"], capture_output=True, text=True).stdout
            self.assertIn("Hello from C++", out)


if __name__ == "__main__":
    unittest.main()
