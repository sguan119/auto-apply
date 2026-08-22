"""tests.test_search_resume_query — planner extract/parse without a live LLM."""

from __future__ import annotations

import pytest

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import LLMSettings
from autoapply.core.search.resume_query import (
    CliResumeQueryClient,
    ResumeQueryError,
    ResumeQueryPlan,
    load_resume_text,
    normalize_queries,
    parse_plan_json,
    plan_queries,
    write_plan,
)

_RESUME = """
Mark Zhou
UX / Product Designer and Game / Level Designer
University of Toronto, Master of Information
Shipped player-facing tools and product UX. Portfolio at example.com.
"""


def test_load_resume_text_from_txt(tmp_path):
    path = tmp_path / "resume.md"
    path.write_text(_RESUME, encoding="utf-8")
    text = load_resume_text(path)
    assert "Product Designer" in text
    assert "Level Designer" in text


def test_pdf_is_refused(tmp_path):
    path = tmp_path / "resume.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ResumeQueryError, match="PDF"):
        load_resume_text(path)


def test_empty_resume_is_refused():
    with pytest.raises(ResumeQueryError, match="empty"):
        load_resume_text("   \n  ")


def test_parse_plan_json_accepts_fenced_object():
    text = """ok
```json
{"queries":["product designer","game designer"],"clusters":["ux","game"],"notes":"two tracks"}
```
"""
    plan = parse_plan_json(text)
    assert plan.queries == ["product designer", "game designer"]
    assert plan.clusters == ["ux", "game"]


def test_parse_plan_json_rejects_ranked_and_page_decision():
    with pytest.raises(ResumeQueryError, match="queries"):
        parse_plan_json('{"ranked":[{"job_key":"linkedin:1","keep":true}]}')
    with pytest.raises(ResumeQueryError, match="queries"):
        parse_plan_json(
            '{"decisions":[],"next_action":{"type":"done","element_id":null,"wait_ms":null}}'
        )


def test_normalize_queries_drops_skills_dups_and_caps():
    out = normalize_queries(
        [
            "Product Designer",
            "product designer",
            "Figma",
            "UX designer",
            "game designer",
            "level designer",
            "interaction designer",
            "this query is way too long to be a board search term at all",
        ]
    )
    assert out == [
        "product designer",
        "ux designer",
        "game designer",
        "level designer",
        "interaction designer",
    ]
    assert "figma" not in out


def test_explicit_queries_skip_the_planner(tmp_path):
    class Boom:
        def plan(self, resume_text: str) -> ResumeQueryPlan:
            raise AssertionError("planner should be skipped")

    bio = tmp_path / "bio.yaml"
    bio.write_text("preferences:\n  target_role_keywords: [ice cream]\n", encoding="utf-8")
    store = YamlBioStore(bio)
    before = store.read_path("preferences.target_role_keywords")

    plan = plan_queries(
        _RESUME,
        client=Boom(),
        queries=["Product Designer", "figma", "Game Designer"],
    )
    assert plan.queries == ["product designer", "game designer"]
    assert "planner skipped" in plan.notes
    assert "Product Designer" in plan.resume_summary or "product" in plan.resume_summary.lower()
    assert store.read_path("preferences.target_role_keywords") == before


def test_cli_client_uses_run_fn_and_schema():
    seen: list[str] = []

    def fake_run(prompt: str) -> str:
        seen.append(prompt)
        return (
            '{"queries":["product designer","game designer"],'
            '"clusters":["product/ux","game/level"],'
            '"yoe_guess":{"min":1,"max":3},'
            '"resume_summary":"UX + game design.","notes":"two tracks"}'
        )

    client = CliResumeQueryClient(LLMSettings(), run_fn=fake_run)
    plan = plan_queries(_RESUME, client=client)
    assert plan.queries == ["product designer", "game designer"]
    assert plan.clusters == ["product/ux", "game/level"]
    assert "queries" in seen[0]
    assert "ranked" not in seen[0]
    assert "PageDecision" not in seen[0]


def test_zero_usable_queries_fail_before_fetch():
    class Empty:
        def plan(self, resume_text: str) -> ResumeQueryPlan:
            return ResumeQueryPlan(queries=["figma", "python"])

    with pytest.raises(ResumeQueryError, match="no usable"):
        plan_queries(_RESUME, client=Empty())


def test_write_plan_json(tmp_path):
    path = tmp_path / "resume_plan.json"
    plan = ResumeQueryPlan(queries=["product designer"], notes="ok")
    wrote = write_plan(plan, path)
    assert wrote == path
    assert "product designer" in path.read_text(encoding="utf-8")
