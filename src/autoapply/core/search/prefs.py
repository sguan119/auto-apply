"""Load the search preference slice from bio + CLI overrides (docs/search-spec.md §4.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from autoapply.core.bio.store import BioStore
from autoapply.core.config import SearchSettings


class EmptySearchKeywords(ValueError):
    """Raised when a run would fetch with zero keywords (search-spec S-2)."""


@dataclass(frozen=True)
class SearchPrefs:
    keywords: list[str]
    locations: list[str] = field(default_factory=list)
    remote: bool = False
    yoe_prefer_min: int = 0
    yoe_prefer_max: int = 3


def _as_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def load_search_prefs(
    bio: BioStore,
    settings: SearchSettings,
    *,
    keywords: Sequence[str] | None = None,
    locations: Sequence[str] | None = None,
) -> SearchPrefs:
    """CLI/run keywords fully replace bio target_role_keywords when provided (spec §4.1)."""
    explicit = _as_string_list(keywords)
    if explicit:
        resolved_keywords = explicit
    else:
        resolved_keywords = _as_string_list(bio.read_path("preferences.target_role_keywords"))

    if not resolved_keywords:
        raise EmptySearchKeywords(
            "search requires at least one keyword (CLI --keyword or preferences.target_role_keywords in bio)"
        )

    explicit_locations = _as_string_list(locations)
    if explicit_locations:
        resolved_locations = explicit_locations
    else:
        resolved_locations = _as_string_list(bio.read_path("preferences.locations"))

    remote = bio.read_path("preferences.remote")
    if not isinstance(remote, bool):
        remote = settings.remote

    return SearchPrefs(
        keywords=resolved_keywords,
        locations=resolved_locations,
        remote=remote,
        yoe_prefer_min=_as_int(bio.read_path("preferences.yoe_prefer_min"), 0),
        yoe_prefer_max=_as_int(bio.read_path("preferences.yoe_prefer_max"), 3),
    )


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
