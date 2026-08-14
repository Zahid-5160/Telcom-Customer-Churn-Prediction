"""Make the terminal safe for the rupee sign.

Windows consoles still default to the cp1252 code page, which has no glyph for
``₹`` - printing one raises ``UnicodeEncodeError`` and kills the command. This
switches the streams to UTF-8 where that is possible, and degrades to replacing
the odd character rather than crashing where it is not.

It is a deliberate, explicit call from the entry points rather than an import
side effect, so importing the library never reaches in and changes a host
application's streams underneath it.
"""

from __future__ import annotations

import sys


def enable_unicode() -> None:
    """Reconfigure stdout and stderr to UTF-8, quietly doing nothing on failure."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # A redirected or already-detached stream; nothing to do.
            pass
