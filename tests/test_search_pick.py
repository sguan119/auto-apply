"""tests.test_search_pick — selected.json is JobRef[] and does not call deliver."""

from __future__ import annotations

import json

import pytest

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import SearchSettings, Settings
from autoapply.core.contracts import SearchJob
from autoapply.core.search.pick import PickError, pick_jobs, resolve_pick_keys
from autoapply.core.search.rerank import RerankItem
from autoapply.core.search.runner import run_search
from autoapply.core.search.fetch.base import SearchAdapter
from autoapply.core.search import store as search_store


class _Adapter(SearchAdapter):
    name = "fake"

    def __init__(self, jobs: list[SearchJob]):
        self._jobs = jobs

    def search(self, *, keywords: str, location: str | None, **kwargs) -> list[SearchJob]:
        return list(self._jobs)


def _job(job_id: str) -> SearchJob:
    return SearchJob(
        platform="linkedin",
        job_id=job_id,
        url=f"https://example.com/jobs/{job_id}",
        title="product designer",
        company="Acme",
        location="Toronto, ON",
        description="Product designer for web and mobile with researchers on the team.",
    )


def _run(tmp_path, jobs: list[SearchJob], *, rerank_client=None):
    settings = Settings(
        search=SearchSettings(sites=["linkedin"], llm_rerank=rerank_client is not None)
    )
    return run_search(
        settings=settings,
        bio_store=YamlBioStore(tmp_path / "bio.yaml"),
        adapter=_Adapter(jobs),
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="pick-run",
        db_path=tmp_path / "app.db",
        rerank_client=rerank_client,
    )


def test_pick_writes_jobref_fields_only(tmp_path):
    _run(tmp_path, [_job("1"), _job("2")])
    path = tmp_path / "selected.json"
    result = pick_jobs(
        ["linkedin:2"],
        run_id="pick-run",
        db_path=tmp_path / "app.db",
        output_path=path,
    )
    assert result.path == path
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert set(payload[0]) == {"platform", "job_id", "url", "title", "company", "score"}
    assert payload[0]["platform"] == "linkedin"
    assert payload[0]["job_id"] == "2"
    assert payload[0]["title"] == "product designer"
    assert payload[0]["company"] == "Acme"
    assert "description" not in payload[0]
    loaded = search_store.load_candidates("pick-run", db_path=tmp_path / "app.db")
    by_id = {c.job_id: c for c in loaded}
    assert by_id["2"].selected is True
    assert by_id["1"].selected is False
    assert payload[0]["score"] == by_id["2"].score


def test_pick_rejects_keys_not_on_shortlist(tmp_path):
    _run(tmp_path, [_job("1")])
    with pytest.raises(PickError, match="not on the current shortlist"):
        pick_jobs(
            ["linkedin:missing"],
            run_id="pick-run",
            db_path=tmp_path / "app.db",
            output_path=tmp_path / "selected.json",
        )


def test_resolve_kept_uses_llm_keep(tmp_path):
    class KeepOne:
        def rerank(self, jobs, *, prefs, bio_excerpt):
            return [
                RerankItem(job_key="linkedin:1", keep=True, rank=1, reason="yes"),
                RerankItem(job_key="linkedin:2", keep=False, rank=None, reason="no"),
            ]

    result = _run(tmp_path, [_job("1"), _job("2")], rerank_client=KeepOne())
    keys = resolve_pick_keys(result.shortlist, kept=True)
    assert keys == ["linkedin:1"]


def test_pick_module_does_not_call_deliver():
    from pathlib import Path

    import autoapply.core.search.pick as pick_mod
    import autoapply.core.search.rerank as rerank_mod
    import autoapply.core.search.runner as runner_mod

    for mod in (pick_mod, rerank_mod, runner_mod):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "run_delivery" not in source
        assert "from autoapply.core.deliver" not in source
        assert "CliLLMClient" not in source
        assert "playwright" not in source.lower()
