from __future__ import annotations

from pathlib import Path

from app.site_rules.base import ArchiveInspection, ArchiveSiteRule
from app.site_rules.wechat import WeChatArticleRule


class ArchiveSiteRuleRegistry:
    def __init__(self, rules: tuple[ArchiveSiteRule, ...]) -> None:
        self.rules = rules

    def inspect(self, url: str, archive_path: Path) -> ArchiveInspection | None:
        for rule in self.rules:
            if not rule.matches_url(url):
                continue
            inspection = rule.inspect(url, archive_path)
            if inspection is not None:
                return inspection
        return None

    def prepare_archive(self, url: str, archive_path: Path) -> None:
        for rule in self.rules:
            if rule.matches_url(url):
                rule.prepare_archive(url, archive_path)

def default_site_rule_registry() -> ArchiveSiteRuleRegistry:
    return ArchiveSiteRuleRegistry((WeChatArticleRule(),))
