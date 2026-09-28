"""Profile and settings data models.

Design notes
------------
* Plain ``dataclasses`` — no third-party validation library, so the frozen
  executable stays small and the models import before Qt exists.
* Every ``from_dict`` is *total*: it accepts arbitrary JSON (including hostile
  or truncated files) and always returns a usable object, substituting
  defaults for anything missing or out of range. A corrupt profile must never
  prevent the app from starting.
* Every ``to_dict`` round-trips: ``from_dict(x.to_dict()) == x``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, TypeVar

from ..constants import (
    DEFAULT_GRID_SIZE,
    DEFAULT_HOTKEYS,
    DEFAULT_PROFILE_NAME,
    DEFAULT_SENDER_NAME,
    DEFAULT_SNAP_THRESHOLD,
    DEFAULT_TARGET_FPS,
    MAX_TARGET_FPS,
    MIN_PARCEL_SIZE,
    MIN_TARGET_FPS,
    PROFILE_SCHEMA_VERSION,
)

# ---------------------------------------------------------------------------
# Coercion helpers
#
# These make every ``from_dict`` tolerant of junk without silently accepting
# nonsense: values are coerced when sensible and clamped to a legal range.
# ---------------------------------------------------------------------------

E = TypeVar("E", bound=Enum)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1", "on"):
            return True
        if lowered in ("false", "no", "0", "off"):
            return False
    return default


def _as_int(value: Any, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def _as_float(
    value: Any, default: float, lo: float | None = None, hi: float | None = None
) -> float:
    try:
        if isinstance(value, bool):
            raise TypeError
        result = float(value)
    except (TypeError, ValueError):
        result = default
    # Reject NaN / inf, which would poison every downstream calculation.
    if result != result or result in (float("inf"), float("-inf")):
        result = default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def _as_str(value: Any, default: str = "", max_len: int = 512) -> str:
    if isinstance(value, str):
        return value[:max_len]
    if value is None:
        return default
    return str(value)[:max_len]


def _as_enum(enum_cls: type[E], value: Any, default: E) -> E:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        for member in enum_cls:
            if str(member.value).lower() == lowered or member.name.lower() == lowered:
                return member
    return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ShapeType(str, Enum):
    """Geometric shape of a single parcel."""

    RECT = "rect"
    ROUNDED_RECT = "rounded_rect"
    ELLIPSE = "ellipse"
    POLYGON = "polygon"


class BooleanOp(str, Enum):
    """How a parcel combines with the parcels below it in the stack."""

    UNION = "union"
    SUBTRACT = "subtract"


class FitMode(str, Enum):
    """How the incoming video is mapped onto the overlay canvas.

    ``NONE`` is the blueprint's literal behaviour: pixels are drawn 1:1 and the
    mask decides what is visible. The other modes exist because an OBS canvas
    and a monitor frequently differ in resolution.
    """

    NONE = "none"
    CONTAIN = "contain"
    COVER = "cover"
    STRETCH = "stretch"


class Anchor(str, Enum):
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class ScaleQuality(str, Enum):
    """Trade-off used when the video has to be resampled to fit the canvas.

    ``FAST`` is nearest-neighbour; ``SMOOTH`` is bilinear. When the source and
    the canvas are the same size neither costs anything, because no transform
    happens at all.
    """

    FAST = "fast"
    SMOOTH = "smooth"


class SourceKind(str, Enum):
    SPOUT = "spout"
    DEMO = "demo"


class GeometryMode(str, Enum):
    PRIMARY = "primary"
    MONITOR = "monitor"
    VIRTUAL = "virtual"
    CUSTOM = "custom"


class HudCorner(str, Enum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


# ---------------------------------------------------------------------------
# Small value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RectSpec:
    """A plain integer rectangle. Qt-free so it is importable anywhere."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: Any) -> RectSpec:
        data = _as_dict(data)
        return cls(
            x=_as_int(data.get("x"), 0),
            y=_as_int(data.get("y"), 0),
            width=_as_int(data.get("width"), 0, lo=0),
            height=_as_int(data.get("height"), 0, lo=0),
        )


# ---------------------------------------------------------------------------
# Parcel
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalise_points(raw: Any) -> list[tuple[float, float]]:
    """Polygon vertices as fractions (0..1) of the parcel's bounding box.

    Storing them normalised means moving or resizing a polygon parcel is the
    same arithmetic as for a rectangle — no per-vertex bookkeeping.
    """
    points: list[tuple[float, float]] = []
    for item in _as_list(raw):
        if isinstance(item, dict):
            px, py = item.get("x"), item.get("y")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            px, py = item[0], item[1]
        else:
            continue
        points.append((_as_float(px, 0.0, 0.0, 1.0), _as_float(py, 0.0, 0.0, 1.0)))
    return points


#: Fallback polygon (a triangle) used when a polygon parcel has too few points.
_DEFAULT_POLYGON: tuple[tuple[float, float], ...] = ((0.5, 0.0), (1.0, 1.0), (0.0, 1.0))


@dataclass
class Parcel:
    """One "kotak/parsel": a hole in the window mask through which video shows."""

    id: str = field(default_factory=_new_id)
    name: str = ""
    x: int = 0
    y: int = 0
    width: int = 480
    height: int = 270
    shape: ShapeType = ShapeType.RECT
    corner_radius: int = 24
    points: list[tuple[float, float]] = field(default_factory=list)
    op: BooleanOp = BooleanOp.UNION
    enabled: bool = True
    locked: bool = False

    # -- derived -----------------------------------------------------------
    @property
    def rect(self) -> RectSpec:
        return RectSpec(self.x, self.y, self.width, self.height)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def display_name(self) -> str:
        return self.name or f"Parcel {self.id[:4]}"

    def effective_points(self) -> list[tuple[float, float]]:
        """Polygon vertices, guaranteed to describe a closed shape."""
        if len(self.points) >= 3:
            return list(self.points)
        return list(_DEFAULT_POLYGON)

    def moved(self, dx: int, dy: int) -> Parcel:
        return replace(self, x=self.x + dx, y=self.y + dy)

    def with_rect(self, rect: RectSpec) -> Parcel:
        return replace(
            self,
            x=rect.x,
            y=rect.y,
            width=max(MIN_PARCEL_SIZE, rect.width),
            height=max(MIN_PARCEL_SIZE, rect.height),
        )

    def clone(self, offset: int = 24) -> Parcel:
        """A copy with a fresh id, nudged so it is visibly distinct."""
        return replace(
            self,
            id=_new_id(),
            name=f"{self.name} copy" if self.name else "",
            x=self.x + offset,
            y=self.y + offset,
            points=list(self.points),
        )

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "shape": self.shape.value,
            "corner_radius": self.corner_radius,
            "op": self.op.value,
            "enabled": self.enabled,
            "locked": self.locked,
        }
        if self.shape is ShapeType.POLYGON or self.points:
            data["points"] = [[round(px, 6), round(py, 6)] for px, py in self.points]
        return data

    @classmethod
    def from_dict(cls, data: Any) -> Parcel:
        data = _as_dict(data)
        shape = _as_enum(ShapeType, data.get("shape"), ShapeType.RECT)
        parcel = cls(
            id=_as_str(data.get("id"), "", max_len=64) or _new_id(),
            name=_as_str(data.get("name"), "", max_len=128),
            x=_as_int(data.get("x"), 0, lo=-100_000, hi=100_000),
            y=_as_int(data.get("y"), 0, lo=-100_000, hi=100_000),
            width=_as_int(data.get("width"), 480, lo=MIN_PARCEL_SIZE, hi=100_000),
            height=_as_int(data.get("height"), 270, lo=MIN_PARCEL_SIZE, hi=100_000),
            shape=shape,
            corner_radius=_as_int(data.get("corner_radius"), 24, lo=0, hi=10_000),
            points=_normalise_points(data.get("points")),
            op=_as_enum(BooleanOp, data.get("op"), BooleanOp.UNION),
            enabled=_as_bool(data.get("enabled"), True),
            locked=_as_bool(data.get("locked"), False),
        )
        if parcel.shape is ShapeType.POLYGON and len(parcel.points) < 3:
            parcel.points = list(_DEFAULT_POLYGON)
        return parcel


# ---------------------------------------------------------------------------
# Settings groups
# ---------------------------------------------------------------------------


@dataclass
class SourceSettings:
    kind: SourceKind = SourceKind.SPOUT
    sender_name: str = DEFAULT_SENDER_NAME
    #: When the named sender is absent, fall back to whichever sender exists.
    auto_select_sender: bool = True
    target_fps: int = DEFAULT_TARGET_FPS
    auto_reconnect: bool = True
    #: Fall back to the built-in test pattern when no sender ever appears, so
    #: the user can still lay out parcels. Off by default: a silent switch to a
    #: test pattern during a live stream would be worse than an empty overlay.
    fallback_to_demo: bool = False
    #: Ask Spout to flip rows during the receive. Cheaper than flipping in the
    #: painter; needed when a sender delivers bottom-up textures.
    invert_y: bool = False
    #: Whether the sender's colour channels are already multiplied by alpha.
    #: True for the OBS "Spout Filter", which composites with the premultiplied
    #: "over" operator. Getting this wrong is not subtle — treating
    #: premultiplied data as straight darkens every antialiased edge.
    premultiplied_alpha: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "sender_name": self.sender_name,
            "auto_select_sender": self.auto_select_sender,
            "target_fps": self.target_fps,
            "auto_reconnect": self.auto_reconnect,
            "fallback_to_demo": self.fallback_to_demo,
            "invert_y": self.invert_y,
            "premultiplied_alpha": self.premultiplied_alpha,
        }

    @classmethod
    def from_dict(cls, data: Any) -> SourceSettings:
        data = _as_dict(data)
        return cls(
            kind=_as_enum(SourceKind, data.get("kind"), SourceKind.SPOUT),
            sender_name=_as_str(data.get("sender_name"), DEFAULT_SENDER_NAME, max_len=256),
            auto_select_sender=_as_bool(data.get("auto_select_sender"), True),
            target_fps=_as_int(
                data.get("target_fps"), DEFAULT_TARGET_FPS, lo=MIN_TARGET_FPS, hi=MAX_TARGET_FPS
            ),
            auto_reconnect=_as_bool(data.get("auto_reconnect"), True),
            fallback_to_demo=_as_bool(data.get("fallback_to_demo"), False),
            invert_y=_as_bool(data.get("invert_y"), False),
            premultiplied_alpha=_as_bool(data.get("premultiplied_alpha"), True),
        )


@dataclass
class DisplaySettings:
    geometry_mode: GeometryMode = GeometryMode.PRIMARY
    monitor_index: int = 0
    custom_rect: RectSpec = field(default_factory=RectSpec)
    fit_mode: FitMode = FitMode.CONTAIN
    anchor: Anchor = Anchor.CENTER
    offset_x: int = 0
    offset_y: int = 0
    zoom: float = 1.0
    opacity: float = 1.0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    scale_quality: ScaleQuality = ScaleQuality.SMOOTH

    def to_dict(self) -> dict[str, Any]:
        return {
            "geometry_mode": self.geometry_mode.value,
            "monitor_index": self.monitor_index,
            "custom_rect": self.custom_rect.to_dict(),
            "fit_mode": self.fit_mode.value,
            "anchor": self.anchor.value,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "zoom": round(self.zoom, 6),
            "opacity": round(self.opacity, 4),
            "flip_horizontal": self.flip_horizontal,
            "flip_vertical": self.flip_vertical,
            "scale_quality": self.scale_quality.value,
        }

    @classmethod
    def from_dict(cls, data: Any) -> DisplaySettings:
        data = _as_dict(data)
        return cls(
            geometry_mode=_as_enum(GeometryMode, data.get("geometry_mode"), GeometryMode.PRIMARY),
            monitor_index=_as_int(data.get("monitor_index"), 0, lo=0, hi=63),
            custom_rect=RectSpec.from_dict(data.get("custom_rect")),
            fit_mode=_as_enum(FitMode, data.get("fit_mode"), FitMode.CONTAIN),
            anchor=_as_enum(Anchor, data.get("anchor"), Anchor.CENTER),
            offset_x=_as_int(data.get("offset_x"), 0, lo=-100_000, hi=100_000),
            offset_y=_as_int(data.get("offset_y"), 0, lo=-100_000, hi=100_000),
            zoom=_as_float(data.get("zoom"), 1.0, lo=0.05, hi=20.0),
            opacity=_as_float(data.get("opacity"), 1.0, lo=0.0, hi=1.0),
            flip_horizontal=_as_bool(data.get("flip_horizontal"), False),
            flip_vertical=_as_bool(data.get("flip_vertical"), False),
            scale_quality=_as_enum(ScaleQuality, data.get("scale_quality"), ScaleQuality.SMOOTH),
        )


@dataclass
class BehaviorSettings:
    click_through: bool = True
    always_on_top: bool = True
    #: Periodically re-assert HWND_TOPMOST; some fullscreen apps steal it.
    #: 0 disables the timer.
    topmost_reassert_ms: int = 3000
    hide_from_taskbar: bool = True
    no_activate: bool = True
    #: WDA_EXCLUDEFROMCAPTURE — hides the overlay from OBS/screen recorders,
    #: which prevents an infinite mirror when you capture your own desktop.
    exclude_from_capture: bool = False
    mask_enabled: bool = True
    overlay_visible: bool = True
    minimize_to_tray: bool = True
    show_panel_on_start: bool = True
    #: Refuse a configuration that would cover the whole screen with an opaque,
    #: non-click-through window the user could not escape from.
    safety_guard: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "click_through": self.click_through,
            "always_on_top": self.always_on_top,
            "topmost_reassert_ms": self.topmost_reassert_ms,
            "hide_from_taskbar": self.hide_from_taskbar,
            "no_activate": self.no_activate,
            "exclude_from_capture": self.exclude_from_capture,
            "mask_enabled": self.mask_enabled,
            "overlay_visible": self.overlay_visible,
            "minimize_to_tray": self.minimize_to_tray,
            "show_panel_on_start": self.show_panel_on_start,
            "safety_guard": self.safety_guard,
        }

    @classmethod
    def from_dict(cls, data: Any) -> BehaviorSettings:
        data = _as_dict(data)
        return cls(
            click_through=_as_bool(data.get("click_through"), True),
            always_on_top=_as_bool(data.get("always_on_top"), True),
            topmost_reassert_ms=_as_int(data.get("topmost_reassert_ms"), 3000, lo=0, hi=600_000),
            hide_from_taskbar=_as_bool(data.get("hide_from_taskbar"), True),
            no_activate=_as_bool(data.get("no_activate"), True),
            exclude_from_capture=_as_bool(data.get("exclude_from_capture"), False),
            mask_enabled=_as_bool(data.get("mask_enabled"), True),
            overlay_visible=_as_bool(data.get("overlay_visible"), True),
            minimize_to_tray=_as_bool(data.get("minimize_to_tray"), True),
            show_panel_on_start=_as_bool(data.get("show_panel_on_start"), True),
            safety_guard=_as_bool(data.get("safety_guard"), True),
        )


@dataclass
class EditorSettings:
    grid_size: int = DEFAULT_GRID_SIZE
    snap_to_grid: bool = True
    snap_to_parcels: bool = True
    snap_to_canvas: bool = True
    snap_threshold: int = DEFAULT_SNAP_THRESHOLD
    show_grid: bool = False
    show_guides: bool = True
    show_labels: bool = True
    show_rulers: bool = False
    #: Dim everything outside the parcels while editing, so the physical
    #: window bounds are obvious.
    backdrop_opacity: float = 0.35

    def to_dict(self) -> dict[str, Any]:
        return {
            "grid_size": self.grid_size,
            "snap_to_grid": self.snap_to_grid,
            "snap_to_parcels": self.snap_to_parcels,
            "snap_to_canvas": self.snap_to_canvas,
            "snap_threshold": self.snap_threshold,
            "show_grid": self.show_grid,
            "show_guides": self.show_guides,
            "show_labels": self.show_labels,
            "show_rulers": self.show_rulers,
            "backdrop_opacity": round(self.backdrop_opacity, 4),
        }

    @classmethod
    def from_dict(cls, data: Any) -> EditorSettings:
        data = _as_dict(data)
        return cls(
            grid_size=_as_int(data.get("grid_size"), DEFAULT_GRID_SIZE, lo=1, hi=512),
            snap_to_grid=_as_bool(data.get("snap_to_grid"), True),
            snap_to_parcels=_as_bool(data.get("snap_to_parcels"), True),
            snap_to_canvas=_as_bool(data.get("snap_to_canvas"), True),
            snap_threshold=_as_int(
                data.get("snap_threshold"), DEFAULT_SNAP_THRESHOLD, lo=0, hi=128
            ),
            show_grid=_as_bool(data.get("show_grid"), False),
            show_guides=_as_bool(data.get("show_guides"), True),
            show_labels=_as_bool(data.get("show_labels"), True),
            show_rulers=_as_bool(data.get("show_rulers"), False),
            backdrop_opacity=_as_float(data.get("backdrop_opacity"), 0.35, lo=0.0, hi=0.95),
        )


@dataclass
class HudSettings:
    enabled: bool = False
    corner: HudCorner = HudCorner.TOP_LEFT
    show_fps: bool = True
    show_source: bool = True
    show_dropped: bool = True
    show_latency: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "corner": self.corner.value,
            "show_fps": self.show_fps,
            "show_source": self.show_source,
            "show_dropped": self.show_dropped,
            "show_latency": self.show_latency,
        }

    @classmethod
    def from_dict(cls, data: Any) -> HudSettings:
        data = _as_dict(data)
        return cls(
            enabled=_as_bool(data.get("enabled"), False),
            corner=_as_enum(HudCorner, data.get("corner"), HudCorner.TOP_LEFT),
            show_fps=_as_bool(data.get("show_fps"), True),
            show_source=_as_bool(data.get("show_source"), True),
            show_dropped=_as_bool(data.get("show_dropped"), True),
            show_latency=_as_bool(data.get("show_latency"), True),
        )


@dataclass
class HotkeySettings:
    """Global hotkeys, stored as human-readable strings ("Ctrl+Alt+M").

    An empty string disables that action's hotkey.
    """

    toggle_editor: str = DEFAULT_HOTKEYS["toggle_editor"]
    toggle_click_through: str = DEFAULT_HOTKEYS["toggle_click_through"]
    toggle_overlay: str = DEFAULT_HOTKEYS["toggle_overlay"]
    toggle_panel: str = DEFAULT_HOTKEYS["toggle_panel"]
    reload_profile: str = DEFAULT_HOTKEYS["reload_profile"]
    panic: str = DEFAULT_HOTKEYS["panic"]

    def as_mapping(self) -> dict[str, str]:
        return {
            "toggle_editor": self.toggle_editor,
            "toggle_click_through": self.toggle_click_through,
            "toggle_overlay": self.toggle_overlay,
            "toggle_panel": self.toggle_panel,
            "reload_profile": self.reload_profile,
            "panic": self.panic,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.as_mapping()

    @classmethod
    def from_dict(cls, data: Any) -> HotkeySettings:
        data = _as_dict(data)
        return cls(
            **{
                action: _as_str(data.get(action), default, max_len=64)
                for action, default in DEFAULT_HOTKEYS.items()
            }
        )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def _default_parcels() -> list[Parcel]:
    """Two side-by-side boxes, matching the blueprint's pseudocode example."""
    return [
        Parcel(name="Box 1", x=100, y=100, width=300, height=300, corner_radius=16),
        Parcel(name="Box 2", x=500, y=100, width=300, height=300, corner_radius=16),
    ]


@dataclass
class Profile:
    """Everything that defines one overlay layout + its behaviour."""

    schema_version: int = PROFILE_SCHEMA_VERSION
    name: str = DEFAULT_PROFILE_NAME
    description: str = ""
    source: SourceSettings = field(default_factory=SourceSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    behavior: BehaviorSettings = field(default_factory=BehaviorSettings)
    editor: EditorSettings = field(default_factory=EditorSettings)
    hud: HudSettings = field(default_factory=HudSettings)
    hotkeys: HotkeySettings = field(default_factory=HotkeySettings)
    parcels: list[Parcel] = field(default_factory=_default_parcels)

    # -- queries -----------------------------------------------------------
    def parcel_by_id(self, parcel_id: str) -> Parcel | None:
        for parcel in self.parcels:
            if parcel.id == parcel_id:
                return parcel
        return None

    def index_of(self, parcel_id: str) -> int:
        for index, parcel in enumerate(self.parcels):
            if parcel.id == parcel_id:
                return index
        return -1

    def active_parcels(self) -> list[Parcel]:
        return [p for p in self.parcels if p.enabled]

    # -- mutation ----------------------------------------------------------
    def replace_parcel(self, parcel: Parcel) -> bool:
        index = self.index_of(parcel.id)
        if index < 0:
            return False
        self.parcels[index] = parcel
        return True

    def remove_parcel(self, parcel_id: str) -> bool:
        index = self.index_of(parcel_id)
        if index < 0:
            return False
        del self.parcels[index]
        return True

    def ensure_unique_ids(self) -> None:
        """Repair duplicate ids, which would otherwise make selection ambiguous."""
        seen: set = set()
        for index, parcel in enumerate(self.parcels):
            if not parcel.id or parcel.id in seen:
                self.parcels[index] = replace(parcel, id=_new_id())
            seen.add(self.parcels[index].id)

    def regenerate_ids(self) -> None:
        """Give every parcel a brand-new id.

        Used when duplicating a profile: ids only have to be unique *within* a
        profile, but leaving the copy sharing them makes the two profiles look
        related to anything that keys on an id, which they are not.
        """
        for index, parcel in enumerate(self.parcels):
            self.parcels[index] = replace(parcel, id=_new_id())

    def copy(self) -> Profile:
        return Profile.from_dict(self.to_dict())

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": self.name,
            "description": self.description,
            "source": self.source.to_dict(),
            "display": self.display.to_dict(),
            "behavior": self.behavior.to_dict(),
            "editor": self.editor.to_dict(),
            "hud": self.hud.to_dict(),
            "hotkeys": self.hotkeys.to_dict(),
            "parcels": [p.to_dict() for p in self.parcels],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Profile:
        data = _as_dict(data)
        raw_parcels = _as_list(data.get("parcels"))
        parcels = [Parcel.from_dict(item) for item in raw_parcels]
        profile = cls(
            schema_version=_as_int(
                data.get("schema_version"), PROFILE_SCHEMA_VERSION, lo=1, hi=1_000
            ),
            name=_as_str(data.get("name"), DEFAULT_PROFILE_NAME, max_len=128)
            or DEFAULT_PROFILE_NAME,
            description=_as_str(data.get("description"), "", max_len=1024),
            source=SourceSettings.from_dict(data.get("source")),
            display=DisplaySettings.from_dict(data.get("display")),
            behavior=BehaviorSettings.from_dict(data.get("behavior")),
            editor=EditorSettings.from_dict(data.get("editor")),
            hud=HudSettings.from_dict(data.get("hud")),
            hotkeys=HotkeySettings.from_dict(data.get("hotkeys")),
            # An explicitly empty parcel list is legal (a fully hidden overlay);
            # only a *missing* key falls back to the starter layout.
            parcels=parcels if "parcels" in data else _default_parcels(),
        )
        profile.ensure_unique_ids()
        return profile

    @classmethod
    def default(cls, name: str = DEFAULT_PROFILE_NAME) -> Profile:
        return cls(name=name)


# ---------------------------------------------------------------------------
# App-level settings (machine state, not part of a profile)
# ---------------------------------------------------------------------------


@dataclass
class AppSettings:
    active_profile: str = DEFAULT_PROFILE_NAME
    log_level: str = "INFO"
    language: str = "id"
    panel_geometry: RectSpec | None = None
    first_run_completed: bool = False

    _LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    _LANGUAGES = ("id", "en")

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_profile": self.active_profile,
            "log_level": self.log_level,
            "language": self.language,
            "panel_geometry": self.panel_geometry.to_dict() if self.panel_geometry else None,
            "first_run_completed": self.first_run_completed,
        }

    @classmethod
    def from_dict(cls, data: Any) -> AppSettings:
        data = _as_dict(data)
        level = _as_str(data.get("log_level"), "INFO", max_len=16).upper()
        language = _as_str(data.get("language"), "id", max_len=8).lower()
        geometry = data.get("panel_geometry")
        return cls(
            active_profile=_as_str(data.get("active_profile"), DEFAULT_PROFILE_NAME, max_len=128)
            or DEFAULT_PROFILE_NAME,
            log_level=level if level in cls._LOG_LEVELS else "INFO",
            language=language if language in cls._LANGUAGES else "id",
            panel_geometry=RectSpec.from_dict(geometry) if isinstance(geometry, dict) else None,
            first_run_completed=_as_bool(data.get("first_run_completed"), False),
        )


def parcels_to_dicts(parcels: Sequence[Parcel]) -> list[dict[str, Any]]:
    """Convenience used by the clipboard / import-export paths."""
    return [p.to_dict() for p in parcels]
