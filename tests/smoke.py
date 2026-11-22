"""C/C++ smoke test for CI. Run with:  python tests/smoke.py

Unlike the unit tests, this never skips. It fails when the real GCC (not Apple Clang),
CMake or Ninja is missing, so a broken CI toolchain cannot turn the compiler tests
into silent skips. Then it builds and runs the two hello examples with the same
command line the launcher uses.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from devkit import system, toolchain  # noqa: E402

EXPECTED = {"c": ("examples/c/01_hello.c", "Hello from C"),
            "cpp": ("examples/cpp/01_hello.cpp", "Hello from C++")}


def main() -> int:
    errors: list[str] = []
    print(f"platform: {system.PLATFORM_NAME}, python {sys.version.split()[0]}")

    for lang in ("c", "cpp"):
        info = toolchain.compiler_info(lang)
        print(f"{lang:>3} compiler: {info.path} ({info.version})")
        if not info.path:
            errors.append(f"no {toolchain.compiler_name(lang)} found")
        elif info.is_clang:
            errors.append(f"{info.path} is Clang, not GCC")

    for tool in ("cmake", "ninja"):
        path = shutil.which(tool)
        print(f"{tool:>12}: {path}")
        if not path:
            errors.append(f"{tool} not on PATH")

    if errors:
        print("\nToolchain incomplete:\n  " + "\n  ".join(errors))
        return 1

    major = toolchain.gcc_major(toolchain.compiler_version("cpp"))
    with tempfile.TemporaryDirectory() as tmp:
        for lang, (rel, expected) in EXPECTED.items():
            opts = toolchain.BuildOptions(language=lang, standard=toolchain.DEFAULT_STANDARD[lang],
                                          werror=True, gcc_major=major)
            out = Path(tmp) / (Path(rel).stem + "_" + lang)
            cmd = toolchain.build_command(toolchain.find_compiler(lang), [ROOT / rel], out, opts)
            print("\n$ " + system.format_cmd(cmd))
            build = subprocess.run(cmd, capture_output=True, text=True, env=system.toolchain_env())
            if build.returncode != 0:
                print(build.stdout + build.stderr)
                errors.append(f"{rel} did not compile")
                continue
            run = subprocess.run([str(out)], capture_output=True, text=True, timeout=30)
            print(run.stdout.rstrip())
            if run.returncode != 0 or expected not in run.stdout:
                errors.append(f"{rel}: {toolchain.describe_exit(run.returncode)}, "
                              f"expected {expected!r} in the output")

    if errors:
        print("\nSmoke test failed:\n  " + "\n  ".join(errors))
        return 1
    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
