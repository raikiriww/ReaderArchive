from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import ManualActionRead


@dataclass(frozen=True)
class ArchiveInspection:
    manual_actions: tuple[ManualActionRead, ...] = ()
    error: str | None = None


class ArchiveSiteRule(Protocol):
    rule_id: str

    def matches_url(self, url: str) -> bool: ...

    def prepare_archive(self, url: str, archive_path: Path) -> None: ...

    def inspect(self, url: str, archive_path: Path) -> ArchiveInspection | None: ...
