"""tests.test_search_rerank — parse/apply LLM ranking without a live CLI."""

from __future__ import annotations

import pytest

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import LLMSettings
from autoapply.core.contracts import SearchCandidate
from autoapply.core.search.prefs import SearchPrefs
from autoapply.core.search.rerank import (
    CliSearchRerankClient,
    MAX_JD_CHARS,
    RerankItem,
    SearchRerankError,
    apply_rerank,
    compact_bio_excerpt,
    parse_rerank_json,
    review_order,
    shortlist_payload,
)


def _candidate(job_id: str, *, rank: int | None, title: str = "UX Designer") -> SearchCandidate:
    return SearchCandidate(
        platform="linkedin",
        job_id=job_id,
        url=f"https://example.com/jobs/{job_id}",
        title=title,
        company="Acme",
        score=0.8,
        prefilter_rank=rank,
        description="x" * (MAX_JD_CHARS + 50) if job_id == "long" else "A product design role.",
    )


def test_parse_rerank_json_accepts_fenced_object():
    text = """here you go
```json
{"ranked":[{"job_key":"linkedin:1","keep":true,"rank":1,"reason":"fit"}]}
```
"""
    items = parse_rerank_json(text)
    assert items == [RerankItem(job_key="linkedin:1", keep=True, rank=1, reason="fit")]


def test_parse_rerank_json_rejects_page_decision():
    with pytest.raises(SearchRerankError, match="ranked"):
        parse_rerank_json(
            '{"decisions":[],"next_action":{"type":"done","element_id":null,"wait_ms":null}}'
        )


def test_apply_rerank_shortlist_only_ignores_unknown_keys():
    shortlisted = _candidate("1", rank=1)
    overflow = _candidate("2", rank=None)
    items = [
        RerankItem(job_key="linkedin:1", keep=True, rank=1, reason="yes"),
        RerankItem(job_key="linkedin:2", keep=True, rank=2, reason="should ignore"),
        RerankItem(job_key="linkedin:ghost", keep=True, rank=3, reason="unknown"),
    ]
    out = {c.job_id: c for c in apply_rerank([shortlisted, overflow], items)}
    assert out["1"].llm_keep is True
    assert out["2"].llm_keep is None
    assert "ghost" not in out


def test_review_order_keep_first():
    kept = _candidate("b", rank=2).model_copy(
        update={"llm_keep": True, "llm_rank": 1, "llm_reason": "best"}
    )
    dropped = _candidate("a", rank=1).model_copy(
        update={"llm_keep": False, "llm_rank": None, "llm_reason": "no"}
    )
    ordered = review_order([dropped, kept])
    assert [c.job_id for c in ordered] == ["b", "a"]


def test_shortlist_payload_truncates_jd():
    rows = shortlist_payload([_candidate("long", rank=1)])
    assert len(rows[0]["description"]) == MAX_JD_CHARS


def test_compact_bio_excerpt_includes_resume_when_provided(tmp_path):
    prefs = SearchPrefs(keywords=["UX designer"], locations=["Toronto, ON"])
    bio = YamlBioStore(tmp_path / "bio.yaml")
    excerpt = compact_bio_excerpt(bio, prefs)
    assert "resume" not in excerpt
    excerpt = compact_bio_excerpt(bio, prefs, resume_excerpt="  dual-track UX and game design  ")
    assert excerpt["resume"] == "dual-track UX and game design"


def test_cli_client_uses_run_fn_and_schema(tmp_path):
    prefs = SearchPrefs(keywords=["UX designer"], locations=["Toronto, ON"])
    bio = YamlBioStore(tmp_path / "bio.yaml")
    seen: list[str] = []

    def fake_run(prompt: str) -> str:
        seen.append(prompt)
        return '{"ranked":[{"job_key":"linkedin:1","keep":false,"rank":null,"reason":"senior"}]}'

    client = CliSearchRerankClient(LLMSettings(), run_fn=fake_run)
    items = client.rerank(
        [_candidate("1", rank=1)],
        prefs=prefs,
        bio_excerpt=compact_bio_excerpt(bio, prefs),
    )
    assert items[0].keep is False
    assert "ranked" in seen[0]
    assert "PageDecision" not in seen[0]
    assert "decisions" not in seen[0]


def test_http_transport_reranks_without_cli(monkeypatch, tmp_path):
    prefs = SearchPrefs(keywords=["UX designer"], locations=["Toronto, ON"])
    bio = YamlBioStore(tmp_path / "bio.yaml")

    def fake_complete(prompt, settings):
        assert settings.transport == "http"
        assert settings.model == "deepseek-chat"
        assert "ranked" in prompt
        return '{"ranked":[{"job_key":"linkedin:1","keep":true,"rank":1,"reason":"fit"}]}'

    monkeypatch.setattr("autoapply.core.search.rerank.complete_prompt", fake_complete)
    client = CliSearchRerankClient(
        LLMSettings(
            transport="http",
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model="ignored",
        ),
        model="deepseek-chat",
        transport="http",
    )
    items = client.rerank(
        [_candidate("1", rank=1)],
        prefs=prefs,
        bio_excerpt=compact_bio_excerpt(bio, prefs),
    )
    assert items[0].keep is True
    assert items[0].rank == 1
