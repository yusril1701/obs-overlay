"""On-disk profile schema migrations.

Every bump of :data:`~obs_overlay.constants.PROFILE_SCHEMA_VERSION` must add a
step here. Steps take and return a raw ``dict`` (never a model instance) so
that a profile written by a much older version is repaired *before* the strict
model layer sees it.

Version history
---------------
1
    The "blueprint" layout: a flat ``boxes`` list of ``[x, y, w, h]`` arrays
    plus a top-level ``sender`` string, mirroring the pseudocode in the
    project blueprint. Hand-written configs may still look like this.
2
    The current layout: grouped settings objects and rich ``parcels``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..constants import PROFILE_SCHEMA_VERSION

logger = logging.getLogger(__name__)

MigrationStep = Callable[[dict[str, Any]], dict[str, Any]]


def _migrate_1_to_2(data: dict[str, Any]) -> dict[str, Any]:
    """Blueprint-era flat layout → grouped settings."""
    result = dict(data)

    # boxes: [[x, y, w, h], ...] -> parcels: [{...}, ...]
    raw_boxes = result.pop("boxes", None)
    if isinstance(raw_boxes, list) and "parcels" not in result:
        parcels: list[dict[str, Any]] = []
        for index, box in enumerate(raw_boxes):
            if isinstance(box, (list, tuple)) and len(box) >= 4:
                x, y, width, height = box[0], box[1], box[2], box[3]
            elif isinstance(box, dict):
                x = box.get("x", 0)
                y = box.get("y", 0)
                width = box.get("w", box.get("width", 300))
                height = box.get("h", box.get("height", 300))
            else:
                continue
            parcels.append(
                {
                    "name": f"Box {index + 1}",
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "shape": "rect",
                }
            )
        result["parcels"] = parcels

    # Top-level scalars -> grouped settings objects.
    source = dict(result.get("source") or {})
    for legacy_key in ("sender", "sender_name", "spout_name"):
        if legacy_key in result:
            source.setdefault("sender_name", result.pop(legacy_key))
    if "fps" in result:
        source.setdefault("target_fps", result.pop("fps"))
    if source:
        result["source"] = source

    behavior = dict(result.get("behavior") or {})
    for legacy_key, new_key in (
        ("click_through", "click_through"),
        ("always_on_top", "always_on_top"),
        ("topmost", "always_on_top"),
    ):
        if legacy_key in result:
            behavior.setdefault(new_key, result.pop(legacy_key))
    if behavior:
        result["behavior"] = behavior

    display = dict(result.get("display") or {})
    if "opacity" in result:
        display.setdefault("opacity", result.pop("opacity"))
    if display:
        result["display"] = display

    result["schema_version"] = 2
    return result


#: Keyed by the version being migrated *from*.
MIGRATIONS: dict[int, MigrationStep] = {
    1: _migrate_1_to_2,
}


def detect_version(data: dict[str, Any]) -> int:
    """Best-effort schema version of a raw profile dict.

    A file with no ``schema_version`` is assumed to be v1 if it carries a
    blueprint-era marker, otherwise it is treated as current — an unversioned
    file written by a hand-editing user is far more likely to be current.
    """
    raw = data.get("schema_version")
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return int(raw)
    if "boxes" in data or "spout_name" in data or "sender" in data:
        return 1
    return PROFILE_SCHEMA_VERSION


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a raw profile dict to the current schema version.

    Unknown *newer* versions are passed through untouched: the tolerant model
    layer will keep whatever it recognises, which degrades far more gracefully
    than refusing to load.
    """
    if not isinstance(data, dict):
        return {"schema_version": PROFILE_SCHEMA_VERSION}

    result = dict(data)
    version = detect_version(result)

    if version > PROFILE_SCHEMA_VERSION:
        logger.warning(
            "Profile schema v%s is newer than supported v%s; unknown fields will be dropped.",
            version,
            PROFILE_SCHEMA_VERSION,
        )
        return result

    # Guard against a malformed step that fails to advance the version.
    guard = 0
    while version < PROFILE_SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            logger.warning("No migration from schema v%s; loading as-is.", version)
            break
        logger.info("Migrating profile schema v%s -> v%s", version, version + 1)
        result = step(result)
        new_version = detect_version(result)
        if new_version <= version:
            logger.error("Migration from v%s did not advance the version; stopping.", version)
            break
        version = new_version
        guard += 1
        if guard > len(MIGRATIONS) + 1:
            logger.error("Migration loop detected; stopping.")
            break

    result["schema_version"] = max(version, PROFILE_SCHEMA_VERSION)
    return result
