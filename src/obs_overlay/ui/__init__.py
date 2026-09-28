"""Qt user interface.

``overlay_window``  the transparent, masked, click-through overlay
``editor``          the interactive parcel editor drawn on that overlay
``control_panel``   the settings window (hidden by default)
``parcel_table``    spreadsheet view of the parcels
``tray``            the system-tray presence and menu
``hud``             the on-overlay statistics panel
``theme`` / ``icons`` / ``widgets``  shared presentation helpers
"""

from __future__ import annotations

__all__ = [
    "ControlPanel",
    "OverlayWindow",
    "ParcelEditor",
    "TrayIcon",
]


def __getattr__(name: str):
    # Imported lazily so that `import obs_overlay.ui` does not pull in every
    # widget module (and therefore all of QtWidgets) before it is needed.
    if name == "OverlayWindow":
        from .overlay_window import OverlayWindow

        return OverlayWindow
    if name == "ControlPanel":
        from .control_panel import ControlPanel

        return ControlPanel
    if name == "ParcelEditor":
        from .editor import ParcelEditor

        return ParcelEditor
    if name == "TrayIcon":
        from .tray import TrayIcon

        return TrayIcon
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
