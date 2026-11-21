"""Configuration actions offered on the Configure page."""

from __future__ import annotations

import webbrowser

from . import system


def git_get(key: str) -> str:
    git = system.find_tool("git")
    if not git:
        return ""
    rc, out = system.run_capture([git, "config", "--global", "--get", key])
    return out.strip() if rc == 0 else ""


def set_git_identity(name: str, email: str, log: system.Log) -> bool:
    git = system.find_tool("git")
    if not git:
        log("error: Git is not installed. Install the Classic pack first.")
        return False
    if not name.strip() or "@" not in email:
        log("error: enter a name and a valid email address.")
        return False
    ok = system.run_stream([git, "config", "--global", "user.name", name.strip()], log) == 0
    ok &= system.run_stream([git, "config", "--global", "user.email", email.strip()], log) == 0
    if ok:
        log("✓ Git identity saved. Use the same email as your GitHub account so commits are linked to you.")
    return ok


def apply_git_defaults(log: system.Log) -> bool:
    git = system.find_tool("git")
    if not git:
        log("error: Git is not installed.")
        return False
    settings = [
        ("init.defaultBranch", "main"),          # same default branch as GitHub
        ("core.autocrlf", "true" if system.IS_WINDOWS else "input"),  # line endings
        ("pull.rebase", "false"),
        ("fetch.prune", "true"),
    ]
    if system.find_code_cli():
        settings.append(("core.editor", "code --wait"))
    ok = True
    for key, value in settings:
        ok &= system.run_stream([git, "config", "--global", key, value], log) == 0
    if ok:
        log("✓ Recommended Git settings applied.")
    return ok


def github_login(log: system.Log) -> None:
    gh = system.find_tool("gh")
    if not gh:
        log("error: GitHub CLI is not installed. Install the GitHub pack first.")
        return
    log("Opening a terminal for 'gh auth login'. Choose GitHub.com, HTTPS, and login with a web browser.")
    system.open_terminal("gh auth login && gh auth setup-git && gh auth status")


def github_status(log: system.Log) -> None:
    gh = system.find_tool("gh")
    if not gh:
        log("error: GitHub CLI is not installed.")
        return
    system.run_stream([gh, "auth", "status"], log)


def open_new_repo_page() -> None:
    webbrowser.open("https://github.com/new")
