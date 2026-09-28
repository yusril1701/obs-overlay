"""PyInstaller hook for the SpoutGL wheel.

Two things PyInstaller cannot work out on its own:

1. ``SpoutGL/__init__.py`` is just ``from ._spoutgl import *``, and ``enums``
   and ``helpers`` are submodules *of the C extension*, so static analysis
   never sees them. They have to be declared.
2. The native library is ``Spout.dll`` — not ``SpoutLibrary.dll``, which is a
   different artifact from the C++ SDK. ``_spoutgl.<abi>.pyd`` imports it at
   load time, so it must sit next to the extension in ``SpoutGL/``.

``collect_dynamic_libs`` is left at its default ``destdir=None``, which
preserves the package-relative directory. Forcing ``destdir='.'`` would put
Spout.dll at the bundle root, where the extension's own directory probe does
not look, and the app would die with "DLL load failed while importing
_spoutgl".
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

hiddenimports = ["SpoutGL.enums", "SpoutGL.helpers"]

binaries = collect_dynamic_libs("SpoutGL")
