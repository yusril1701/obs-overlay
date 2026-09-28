"""Crash-safe profile and settings storage.

Writes go through a temp file in the destination directory followed by
``os.replace``, which is atomic on both NTFS and POSIX. A power cut can
therefore leave either the old file or the new file, never a half-written one —
which matters because the overlay saves on every layout tweak.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .. import paths
from ..constants import DEFAULT_PROFILE_NAME, PROFILE_SUFFIX
from .migrations import migrate
from .models import AppSettings, Profile

logger = logging.getLogger(__name__)

#: Characters Windows forbids in filenames, plus path separators.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
#: Device names Windows refuses to use as a filename, whatever the extension.
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ProfileStoreError(RuntimeError):
    """Raised when a profile cannot be read or written."""


def slugify(name: str) -> str:
    """Turn a display name into a safe, stable filename stem.

    Guarantees a non-empty result that Windows will accept.
    """
    cleaned = _UNSAFE_CHARS.sub("_", (name or "").strip())
    cleaned = cleaned.strip(" .")  # Windows drops trailing dots and spaces
    cleaned = re.sub(r"\s+", "_", cleaned)
    if not cleaned:
        cleaned = "profile"
    if cleaned.upper() in _RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned[:80]


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Serialise ``payload`` to ``path`` atomically.

    The temp file is created in the destination directory so that
    ``os.replace`` stays on one filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)

    # Not opened with `with` at construction: the file has to outlive its own
    # handle so that os.replace can rename it after it is closed and flushed.
    # It is closed by the inner `with` below and removed in the `finally`.
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=str(path.parent),
        prefix=f".{path.stem}.",
        suffix=".tmp",
        delete=False,
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        raise ProfileStoreError(f"Failed to write {path}: {exc}") from exc
    finally:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object, raising :class:`ProfileStoreError` on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileStoreError(f"Failed to read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileStoreError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileStoreError(f"{path.name} does not contain a JSON object")
    return data


def quarantine(path: Path) -> Path | None:
    """Move a corrupt file aside so the app can start with a fresh one.

    Returns the new location, or ``None`` if it could not be moved.
    """
    for index in range(1, 100):
        candidate = path.with_suffix(path.suffix + f".corrupt{'' if index == 1 else index}")
        if not candidate.exists():
            try:
                shutil.move(str(path), str(candidate))
                logger.warning("Quarantined unreadable file %s -> %s", path.name, candidate.name)
                return candidate
            except OSError as exc:  # pragma: no cover
                logger.error("Could not quarantine %s: %s", path, exc)
                return None
    return None


class ConfigStore:
    """Owns the profiles directory and the app-level settings file."""

    def __init__(
        self,
        profiles_dir: Path | None = None,
        settings_file: Path | None = None,
    ) -> None:
        self._profiles_dir = Path(profiles_dir) if profiles_dir else paths.profiles_dir()
        self._settings_file = Path(settings_file) if settings_file else paths.settings_path()

    # -- locations ---------------------------------------------------------
    @property
    def profiles_dir(self) -> Path:
        return self._profiles_dir

    @property
    def settings_file(self) -> Path:
        return self._settings_file

    def profile_path(self, name: str) -> Path:
        return self._profiles_dir / f"{slugify(name)}{PROFILE_SUFFIX}"

    def ensure_dirs(self) -> None:
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        self._settings_file.parent.mkdir(parents=True, exist_ok=True)

    # -- listing -----------------------------------------------------------
    def list_profiles(self) -> list[str]:
        """Display names of every stored profile, sorted case-insensitively.

        The display name comes from inside the file when readable, so renaming
        a file by hand does not lose the profile.
        """
        if not self._profiles_dir.is_dir():
            return []
        names: list[str] = []
        for path in sorted(self._profiles_dir.glob(f"*{PROFILE_SUFFIX}")):
            try:
                data = read_json(path)
                name = data.get("name")
                names.append(name if isinstance(name, str) and name.strip() else path.stem)
            except ProfileStoreError:
                names.append(path.stem)
        # De-duplicate while keeping order stable.
        seen = set()
        unique = []
        for name in names:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return sorted(unique, key=str.casefold)

    def exists(self, name: str) -> bool:
        return self.profile_path(name).is_file()

    # -- profiles ----------------------------------------------------------
    def load_profile(self, name: str) -> Profile:
        """Load a profile by display name, migrating it if needed.

        A missing file yields a default profile carrying that name. A corrupt
        file is quarantined and likewise replaced, so the app always starts.
        """
        path = self.profile_path(name)
        if not path.is_file():
            logger.info("Profile %r not found; using defaults.", name)
            return Profile.default(name)

        try:
            raw = read_json(path)
        except ProfileStoreError as exc:
            logger.error("%s", exc)
            quarantine(path)
            return Profile.default(name)

        migrated = migrate(raw)
        profile = Profile.from_dict(migrated)
        # The on-disk display name wins over the filename-derived lookup key.
        if not profile.name:
            profile.name = name

        if migrated.get("schema_version") != raw.get("schema_version"):
            logger.info("Profile %r migrated; rewriting.", profile.name)
            try:
                self.save_profile(profile)
            except ProfileStoreError as exc:  # pragma: no cover
                logger.warning("Could not rewrite migrated profile: %s", exc)
        return profile

    def save_profile(self, profile: Profile) -> Path:
        self.ensure_dirs()
        path = self.profile_path(profile.name)
        atomic_write_json(path, profile.to_dict())
        logger.debug("Saved profile %r to %s", profile.name, path)
        return path

    def delete_profile(self, name: str) -> bool:
        path = self.profile_path(name)
        if not path.is_file():
            return False
        try:
            path.unlink()
        except OSError as exc:
            raise ProfileStoreError(f"Failed to delete {path}: {exc}") from exc
        logger.info("Deleted profile %r", name)
        return True

    def rename_profile(self, old_name: str, new_name: str) -> Profile:
        """Rename in place. Raises if the target already exists."""
        if slugify(old_name) == slugify(new_name):
            profile = self.load_profile(old_name)
            profile.name = new_name
            self.save_profile(profile)
            return profile
        if self.exists(new_name):
            raise ProfileStoreError(f"A profile named {new_name!r} already exists.")
        profile = self.load_profile(old_name)
        profile.name = new_name
        self.save_profile(profile)
        self.delete_profile(old_name)
        return profile

    def duplicate_profile(self, name: str, new_name: str) -> Profile:
        if self.exists(new_name):
            raise ProfileStoreError(f"A profile named {new_name!r} already exists.")
        profile = self.load_profile(name).copy()
        profile.name = new_name
        profile.regenerate_ids()
        self.save_profile(profile)
        return profile

    # -- import / export ---------------------------------------------------
    def export_profile(self, profile: Profile, destination: Path) -> Path:
        destination = Path(destination)
        atomic_write_json(destination, profile.to_dict())
        return destination

    def import_profile(self, source: Path, new_name: str | None = None) -> Profile:
        raw = read_json(Path(source))
        profile = Profile.from_dict(migrate(raw))
        if new_name:
            profile.name = new_name
        # Never silently overwrite an existing profile on import.
        base = profile.name or DEFAULT_PROFILE_NAME
        candidate = base
        suffix = 2
        while self.exists(candidate):
            candidate = f"{base} ({suffix})"
            suffix += 1
            if suffix > 999:  # pragma: no cover - pathological
                raise ProfileStoreError("Too many profiles with that name.")
        profile.name = candidate
        self.save_profile(profile)
        return profile

    # -- app settings ------------------------------------------------------
    def load_settings(self) -> AppSettings:
        path = self._settings_file
        if not path.is_file():
            return AppSettings()
        try:
            return AppSettings.from_dict(read_json(path))
        except ProfileStoreError as exc:
            logger.error("%s", exc)
            quarantine(path)
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> Path:
        self.ensure_dirs()
        atomic_write_json(self._settings_file, settings.to_dict())
        return self._settings_file

    # -- bootstrap ---------------------------------------------------------
    def bootstrap(self) -> None:
        """Make sure a usable default profile exists on first run."""
        self.ensure_dirs()
        if not self.list_profiles():
            logger.info("No profiles found; creating %r.", DEFAULT_PROFILE_NAME)
            self.save_profile(Profile.default())
