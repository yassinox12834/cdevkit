# Changelog

All notable changes to C/C++ DevKit. Versions follow [Semantic Versioning](https://semver.org/).

## [1.4.0] - 2026-11-28

Name: **1.4.0 "Run modes"**. New features that change nothing you relied on, so a minor version.

### Added
- **Run modes.** *What F5 does*, in the launcher's *Run* section, offers seven ways to run a file:
  - **Run here** (as before) and **Run in a terminal** (replaces the *Run in a separate terminal* checkbox; your old choice is kept).
  - **Make a standalone executable**: `-O2`, stripped and statically linked into `dist/`, not run. **Show executable** opens its folder.
  - **Make a standalone executable and run it**: the same, then started in a terminal without GCC on PATH.
  - **Check against expected output**: compares the output with an *Expected output* box or `<name>.out` / `<name>.ans`, with input from the *Input* box or `<name>.in`. Says *Accepted* or names the first different line.
  - **Benchmark**: runs 2 to 1000 times with the output hidden, shows fastest, median, mean and slowest.
  - **Debug in a terminal**: a `-O0 -g` build opened in GDB (LLDB on macOS).
- The run button is named after the mode (*Run*, *Make exe*, *Check*, *Benchmark*...); the mode is remembered.
- **Run as** submenu in the explorer's right-click menu.
- A moving bar next to the status while something runs.

### Changed
- The explorer scans folders on a background thread. Opening a big folder, a file appearing, or coming back to the window no longer freezes the interface (a 2 400-file folder blocked it for about half a second before, on every return to the window).
- Rescans when the window comes back to the front happen at most once a second, so closing a menu or a dialog no longer triggers one.
- Settings are written to disk once, 0.4 s after the last change, instead of on every click: moving through the tree with the arrow keys stays smooth.
- The tree redraws in one go (no flicker) and scrolls by pixels instead of whole rows; the options panel and the setup pages scroll further per wheel step.
- `dist/` is left out of the explorer, like `build/`.

### Fixed
- Scrolling the options panel with the mouse wheel changed the C/C++ standard when the pointer passed over the list. Lists and number boxes now ignore the wheel until clicked (launcher and setup app).
- Choosing another file while a build ran made the build finish in the new file's folder (wrong header list, wrong working directory). A build now keeps the file it started with.
- The status said *Ready* while the GCC check was still running, and stayed on *Compiling...* when a program could not start.
- A missing terminal emulator on Linux is reported in the Output panel instead of failing silently.

### Tests
- 111 to 125: output comparison, standalone and debug options, sample files, timings, a 2 400-file scan that must not stall the window, the mouse-wheel fix, and off-screen runs of the standalone, check and benchmark modes (the standalone executable is run with an empty environment to prove it needs nothing).

## [1.3.0] - 2026-11-23

### Added
- **Launcher explorer.** *Open folder...* (`Ctrl+Shift+O`) shows a project folder as a tree on the left of the launcher, like VS Code's explorer.
  - C, C++ and header files each have their own icon.
  - A **green dot** marks every file that defines `main()`: the files **F5** can build and run.
  - Click a file to make it the current one; double-click (or `Enter`) opens it in VS Code; right-click for **Run**, **Build**, **Open in VS Code** and **Show in file manager**.
  - Opening a folder selects its first runnable file, so **F5** works straight away.
  - The tree follows the disk: added, renamed and deleted files appear by themselves, and the window rescans when it comes back to the front, so a `main()` added in VS Code gets its dot.
  - `build/`, `cmake-build-*`, hidden and empty folders are left out. **Show other files** lists the rest of the folder too.
  - A summary under the tree counts C, C++ and header files and how many can run.
  - The open folder is remembered between sessions.
- `launcher_app.py <file or folder>` opens a file or a folder directly.
- `CHANGELOG.md`.

### Changed
- The launcher window is wider (1440 x 820 by default, 1180 x 600 at least) to fit the explorer.
- *Edit* is now **Edit in VS Code**; *Open file...* and *Open folder...* sit side by side.
- Context menus use the app's dark theme.
- New screenshot of the launcher in the README.

### Tests
- 103 to 111: `has_main()` on tricky code (comments, strings, raw strings, prototypes, members), folder scanning, skipped folders, the file limit, rescans after an edit, and three off-screen GUI tests of the explorer.

## [1.2.0] - 2026-11-22

### Changed
- The interface moved from CustomTkinter to Qt (PySide6). CustomTkinter froze the window when scrolling.
- Console output is drawn about 25 times a second in slices, with a capped backlog: a program printing 200 000 lines no longer blocks the window.
- Editor habits (format on save...) moved from global VS Code settings to each project; settings backups are dated and the last five kept.

### Added
- **Cancel** button in the setup app; **Stop** in the launcher also stops a build.
- Rebuild stamps (`build/<name>.stamp.json`): the launcher rebuilds when an option, the compiler or an included header changes.
- Windows: MSYS2 goes first on the user PATH, and **Verify** names another MinGW that comes first.
- New projects get a `.clangd` pointing at `build/debug`.
- `uv` pinned to 0.13.9 and checked against its SHA-256.

### Fixed
- A relative file path no longer fails to build.
- Arch Linux uses `pacman -Syu` instead of the unsupported partial upgrade.
- Linux: unknown package names are skipped before the root step; a failed step does not ask for the password again.
- winget progress bars no longer flood the log.
- Every command has a timeout and can be cancelled, with its whole process tree.

### Tests
- 22 to 103, including off-screen GUI tests that measure how long the window stops responding.

## [1.1.0] - 2026-11-22

### Added
- CI on Windows, macOS and Linux (Python 3.10 and 3.13), with a C/C++ smoke test.

## [1.0.0] - 2026-11-21

- First release: setup app (packs, configure, verify) and launcher.

[1.4.0]: https://github.com/yassinox12834/cdevkit/compare/1.3.0...1.4.0
[1.3.0]: https://github.com/yassinox12834/cdevkit/compare/1.2.0...1.3.0
[1.2.0]: https://github.com/yassinox12834/cdevkit/compare/1.1.0...1.2.0
[1.1.0]: https://github.com/yassinox12834/cdevkit/compare/1.0.0...1.1.0
[1.0.0]: https://github.com/yassinox12834/cdevkit/releases/tag/1.0.0
