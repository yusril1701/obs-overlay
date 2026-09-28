"""Runtime hook: make Spout.dll findable before SpoutGL is imported.

Belt and braces. PyInstaller normally collects ``Spout.dll`` alongside the
extension module and the loader's default search covers it, but on Windows the
DLL search path for an implicitly linked dependency is easy to disturb (a
different working directory, a ``PATH`` full of other Spout builds). Adding the
bundled directory explicitly makes the import deterministic.

Failures here are swallowed: SpoutGL is optional at runtime — the app falls
back to its test-pattern source and reports the problem in the UI — so a hook
that cannot find the directory must not prevent startup.
"""

import os
import sys


def _register_spout_dll_directory() -> None:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return

    candidate = os.path.join(base, "SpoutGL")
    if not os.path.isdir(candidate):
        return

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        try:
            add_dll_directory(candidate)
        except OSError:
            pass

    os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")


try:
    _register_spout_dll_directory()
except Exception:
    pass
