"""Small JSON file cache for slow-changing lookups (profiles, CIKs, market caps)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)


class JsonCache:
    """Key -> (stored_at, value). Thread-safe; written atomically by `save`."""

    def __init__(self, path: Path, now: datetime) -> None:
        self._path = path
        self._now = now
        self._lock = Lock()
        self._entries: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError) as exc:
            log.warning("ignoring unreadable cache %s: %s", self._path, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key: str, max_age: timedelta) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
        if not isinstance(entry, dict) or "at" not in entry:
            return None
        try:
            stored = datetime.fromisoformat(entry["at"])
        except (TypeError, ValueError):
            return None
        return entry.get("value") if self._now - stored <= max_age else None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._entries[key] = {"at": self._now.isoformat(), "value": value}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            text = json.dumps(self._entries, ensure_ascii=False)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            os.replace(tmp, self._path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
