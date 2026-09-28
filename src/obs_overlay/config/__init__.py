"""Typed, versioned configuration for the overlay.

``models``      dataclasses describing a profile and the app-level settings
``migrations``  upgrade paths between on-disk schema versions
``store``       atomic, crash-safe load/save plus profile management
"""

from __future__ import annotations

from .models import (
    Anchor,
    AppSettings,
    BehaviorSettings,
    BooleanOp,
    DisplaySettings,
    EditorSettings,
    FitMode,
    GeometryMode,
    HotkeySettings,
    HudCorner,
    HudSettings,
    Parcel,
    Profile,
    RectSpec,
    ScaleQuality,
    ShapeType,
    SourceKind,
    SourceSettings,
)
from .store import ConfigStore, ProfileStoreError

__all__ = [
    "Anchor",
    "AppSettings",
    "BehaviorSettings",
    "BooleanOp",
    "ConfigStore",
    "DisplaySettings",
    "EditorSettings",
    "FitMode",
    "GeometryMode",
    "HotkeySettings",
    "HudCorner",
    "HudSettings",
    "Parcel",
    "Profile",
    "ProfileStoreError",
    "RectSpec",
    "ScaleQuality",
    "ShapeType",
    "SourceKind",
    "SourceSettings",
]
