# Changelog

All notable changes to C/C++ DevKit. Versions follow [Semantic Versioning](https://semver.org/).

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

[1.3.0]: https://github.com/yassinox12834/cdevkit/compare/1.2.0...1.3.0
[1.2.0]: https://github.com/yassinox12834/cdevkit/compare/1.1.0...1.2.0
[1.1.0]: https://github.com/yassinox12834/cdevkit/compare/1.0.0...1.1.0
[1.0.0]: https://github.com/yassinox12834/cdevkit/releases/tag/1.0.0
