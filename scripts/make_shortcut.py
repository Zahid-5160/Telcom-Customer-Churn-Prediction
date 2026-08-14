"""Create a desktop shortcut that opens the Retain dashboard in two clicks.

Run it with ``python main.py shortcut`` (or ``python scripts/make_shortcut.py``).

Windows gets a real ``.lnk`` with the project icon. macOS and Linux get a small
launcher script on the Desktop instead, since neither has an equivalent of the
Windows shell link.

The shortcut itself is never committed: it stores an absolute path that is only
valid on the machine that made it. This script is committed instead, so anybody
cloning the repository can generate their own in one command.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ICON = PROJECT_ROOT / "assets" / "retain.ico"
SHORTCUT_NAME = "Retain Dashboard"
DESCRIPTION = "Open the Retain employee retention dashboard"


def desktop_dir() -> Path:
    """Find the user's Desktop, falling back to the home directory."""
    if sys.platform == "win32":
        try:
            import winreg

            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                return Path(winreg.QueryValueEx(handle, "Desktop")[0])
        except Exception:
            pass

    for candidate in (Path.home() / "Desktop", Path.home() / "Escritorio", Path.home()):
        if candidate.is_dir():
            return candidate
    return Path.home()


def _windows(target_dir: Path) -> Path:
    """Create a .lnk via the Windows scripting host."""
    link = target_dir / f"{SHORTCUT_NAME}.lnk"
    launcher = PROJECT_ROOT / "Launch Dashboard.bat"

    # PowerShell is the dependency-free way to build a shell link; the
    # alternative is the pywin32 package, which is a heavy install for one file.
    script = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}')
$s.TargetPath = '{launcher}'
$s.WorkingDirectory = '{PROJECT_ROOT}'
$s.Description = '{DESCRIPTION}'
$s.WindowStyle = 7
{f"$s.IconLocation = '{ICON},0'" if ICON.exists() else ""}
$s.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
    )
    return link


def _posix(target_dir: Path) -> Path:
    """Create an executable launcher script on macOS or Linux."""
    link = target_dir / f"{SHORTCUT_NAME}.command" if sys.platform == "darwin" else (
        target_dir / f"{SHORTCUT_NAME}.sh"
    )
    link.write_text(
        f'#!/usr/bin/env bash\ncd "{PROJECT_ROOT}"\nexec "{sys.executable}" main.py serve\n',
        encoding="utf-8",
    )
    link.chmod(link.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return link


def create() -> bool:
    """Create the shortcut. Returns True on success."""
    launcher = PROJECT_ROOT / "Launch Dashboard.bat"
    if sys.platform == "win32" and not launcher.exists():
        print(f"  [X] Missing {launcher.name} - is the project complete?")
        return False

    target_dir = desktop_dir()
    try:
        link = _windows(target_dir) if sys.platform == "win32" else _posix(target_dir)
    except subprocess.CalledProcessError as exc:
        print("  [X] Could not create the shortcut.")
        print(f"      {(exc.stderr or b'').decode(errors='replace').strip()[:300]}")
        return False
    except OSError as exc:
        print(f"  [X] Could not write to {target_dir}: {exc}")
        return False

    print(f"  Shortcut created: {link}")
    print("  Double-click it to open the dashboard.")
    if not ICON.exists() and sys.platform == "win32":
        print("  (No icon found - run `python assets/make_icon.py` to generate one.)")
    return True


if __name__ == "__main__":
    sys.exit(0 if create() else 1)
