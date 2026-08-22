"""tests.test_search_prefs — keyword/location resolution (search-spec §4.1)."""

from __future__ import annotations

import pytest

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import SearchSettings
from autoapply.core.search.prefs import EmptySearchKeywords, load_search_prefs


def test_explicit_keywords_replace_bio_keywords(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    store.write_path("preferences.target_role_keywords", ["UX designer"])
    store.write_path("preferences.locations", ["Toronto, ON"])
    prefs = load_search_prefs(
        store,
        SearchSettings(),
        keywords=["software engineer"],
    )
    assert prefs.keywords == ["software engineer"]
    assert prefs.locations == ["Toronto, ON"]


def test_bio_keywords_used_when_cli_omits_them(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    store.write_path("preferences.target_role_keywords", ["product designer"])
    store.write_path("preferences.remote", True)
    prefs = load_search_prefs(store, SearchSettings(remote=False))
    assert prefs.keywords == ["product designer"]
    assert prefs.remote is True


def test_empty_keywords_raise(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    with pytest.raises(EmptySearchKeywords):
        load_search_prefs(store, SearchSettings(), keywords=[])


def test_yoe_prefs_read_from_bio(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    store.write_path("preferences.target_role_keywords", ["UX designer"])
    store.write_path("preferences.yoe_prefer_min", 0)
    store.write_path("preferences.yoe_prefer_max", 5)
    prefs = load_search_prefs(store, SearchSettings())
    assert prefs.yoe_prefer_min == 0
    assert prefs.yoe_prefer_max == 5
