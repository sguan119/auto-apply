"""tests.test_search_runner — fetch orchestration without live job boards."""

from __future__ import annotations

from datetime import datetime, timezone

from autoapply.core.bio.store import YamlBioStore
from autoapply.core.config import SearchSettings, Settings
from autoapply.core.contracts import (
    DeliveryRecord,
    DeliveryStatus,
    JobRef,
    SearchJob,
)
from autoapply.core.search.fetch.base import SearchAdapter
from autoapply.core.search.runner import run_search
from autoapply.core.storage import repository


class FakeAdapter(SearchAdapter):
    name = "fake"

    def __init__(self, jobs_by_keyword: dict[str, list[SearchJob]] | None = None, fail_sites: bool = False):
        self.jobs_by_keyword = jobs_by_keyword or {}
        self.calls: list[tuple[str, str | None]] = []
        self.fail_sites = fail_sites

    def search(self, *, keywords: str, location: str | None, **kwargs) -> list[SearchJob]:
        self.calls.append((keywords, location))
        if self.fail_sites:
            raise RuntimeError("board down")
        return list(self.jobs_by_keyword.get(keywords, []))


def _job(job_id: str, keyword: str = "ux") -> SearchJob:
    return SearchJob(
        platform="linkedin",
        job_id=job_id,
        url=f"https://example.com/jobs/{job_id}",
        title=f"{keyword} designer",
        company="Acme",
        location="Toronto, ON",
        description=(
            "We are hiring a designer to work on product experiences across "
            "web and mobile platforms with researchers."
        ),
    )


def _settings(**kwargs) -> Settings:
    kwargs.setdefault("llm_rerank", False)
    return Settings(search=SearchSettings(**kwargs))


def test_run_search_dumps_json_and_queries_each_keyword_location(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    adapter = FakeAdapter(
        {
            "product designer": [_job("1", "product")],
            "UX designer": [_job("2", "UX")],
        }
    )
    settings = _settings(sites=["linkedin"], results_wanted=10)
    result = run_search(
        settings=settings,
        bio_store=store,
        adapter=adapter,
        keywords=["product designer", "UX designer"],
        locations=["Toronto, ON"],
        output_root=tmp_path / "runs",
        run_id="run-test",
        db_path=tmp_path / "app.db",
    )
    assert result.summary.fetched == 2
    assert result.summary.failed_reason is None
    assert {job.job_id for job in result.jobs} == {"1", "2"}
    assert adapter.calls == [
        ("product designer", "Toronto, ON"),
        ("UX designer", "Toronto, ON"),
    ]
    jobs_file = result.output_dir / "jobs.json"
    assert jobs_file.exists()
    assert (result.output_dir / "candidates.json").exists()
    text = jobs_file.read_text(encoding="utf-8")
    assert "product designer" in text
    assert str(result.output_dir).endswith("run-test")
    assert result.summary.shortlisted >= 1
    assert all(c.prefilter_rank is not None for c in result.shortlist)


def test_one_query_failure_does_not_abort_the_run(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")

    class PartialFailAdapter(SearchAdapter):
        name = "partial"

        def search(self, *, keywords: str, location: str | None, **kwargs) -> list[SearchJob]:
            if keywords == "bad":
                raise RuntimeError("timeout")
            return [_job("ok")]

    result = run_search(
        settings=_settings(sites=["indeed"]),
        bio_store=store,
        adapter=PartialFailAdapter(),
        keywords=["bad", "good"],
        locations=["Remote"],
        output_root=tmp_path / "runs",
        run_id="partial",
        db_path=tmp_path / "app.db",
    )
    assert result.summary.fetched == 1
    assert result.jobs[0].job_id == "ok"
    assert result.summary.failed_reason is None


def test_all_queries_failed_sets_reason(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    result = run_search(
        settings=_settings(),
        bio_store=store,
        adapter=FakeAdapter(fail_sites=True),
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="fail",
        db_path=tmp_path / "app.db",
    )
    assert result.summary.fetched == 0
    assert result.summary.failed_reason == "all_queries_failed"


def test_duplicate_and_delivered_keys_are_dropped(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    db_path = tmp_path / "app.db"
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    repository.record_delivery(
        DeliveryRecord(
            job=JobRef(
                platform="linkedin",
                job_id="delivered",
                url="https://example.com/jobs/delivered",
                title="Product Designer",
                company="Acme",
                score=0.9,
            ),
            status=DeliveryStatus.SUCCEEDED,
            run_id="old",
            started_at=now,
            finished_at=now,
        ),
        db_path=db_path,
    )
    adapter = FakeAdapter(
        {
            "product designer": [
                _job("dup", "product"),
                _job("dup", "product"),
                _job("delivered", "product"),
                _job("fresh", "product"),
            ]
        }
    )
    result = run_search(
        settings=_settings(sites=["linkedin"]),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="dedupe",
        db_path=db_path,
    )
    assert result.summary.fetched == 4
    assert result.summary.after_dedupe == 3
    by_id = {c.job_id: c for c in result.candidates}
    assert by_id["delivered"].drop_reason == "already_delivered"
    assert by_id["fresh"].drop_reason is None
    assert by_id["fresh"].prefilter_rank is not None
    assert by_id["delivered"].prefilter_rank is None


def test_second_run_marks_previous_keys_already_seen(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    db_path = tmp_path / "app.db"
    adapter = FakeAdapter({"product designer": [_job("keep", "product")]})
    settings = _settings(sites=["linkedin"])
    first = run_search(
        settings=settings,
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="one",
        db_path=db_path,
    )
    assert first.shortlist[0].job_id == "keep"
    second = run_search(
        settings=settings,
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="two",
        db_path=db_path,
    )
    assert second.candidates[0].drop_reason == "already_seen"
    assert second.summary.shortlisted == 0
    from autoapply.core.search import store as search_store

    assert search_store.current_run_id(db_path) == "two"
    assert search_store.load_shortlist(db_path=db_path) == []


class _RecordingRerank:
    def __init__(self, items=None, error: Exception | None = None):
        self.items = items
        self.error = error
        self.seen_keys: list[str] = []

    def rerank(self, jobs, *, prefs, bio_excerpt):
        self.seen_keys = [f"{j.platform}:{j.job_id}" for j in jobs]
        self.bio_excerpt = bio_excerpt
        if self.error is not None:
            raise self.error
        if self.items is not None:
            return self.items
        from autoapply.core.search.rerank import RerankItem

        return [
            RerankItem(job_key=key, keep=True, rank=i, reason="match")
            for i, key in enumerate(self.seen_keys, start=1)
        ]


def test_rerank_only_sees_shortlist_and_sets_keep(tmp_path):
    from autoapply.core.search.rerank import RerankItem

    store = YamlBioStore(tmp_path / "bio.yaml")
    adapter = FakeAdapter(
        {
            "product designer": [
                _job("keep", "product"),
                _job("also", "product"),
            ]
        }
    )
    client = _RecordingRerank(
        items=[
            RerankItem(job_key="linkedin:keep", keep=True, rank=1, reason="role match"),
            RerankItem(job_key="linkedin:also", keep=False, rank=None, reason="weaker"),
        ]
    )
    result = run_search(
        settings=_settings(sites=["linkedin"], llm_rerank=True, shortlist_cap=20),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="rerank",
        db_path=tmp_path / "app.db",
        rerank_client=client,
    )
    assert set(client.seen_keys) == {"linkedin:keep", "linkedin:also"}
    by_id = {c.job_id: c for c in result.candidates}
    assert by_id["keep"].llm_keep is True
    assert by_id["keep"].llm_rank == 1
    assert by_id["also"].llm_keep is False
    assert result.shortlist[0].job_id == "keep"
    assert result.summary.llm_kept == 1


def test_rerank_skips_cap_overflow_and_dropped_jobs(tmp_path):
    from autoapply.core.search.rerank import RerankItem

    store = YamlBioStore(tmp_path / "bio.yaml")
    adapter = FakeAdapter(
        {
            "product designer": [
                _job("top", "product"),
                _job("overflow", "product"),
                SearchJob(
                    platform="linkedin",
                    job_id="junk",
                    url="https://example.com/jobs/junk",
                    title="Warehouse Associate",
                    company="Acme",
                    description="Loading docks and pallets all day with forklifts.",
                ),
            ]
        }
    )
    client = _RecordingRerank(
        items=[RerankItem(job_key="linkedin:top", keep=True, rank=1, reason="ok")]
    )
    result = run_search(
        settings=_settings(
            sites=["linkedin"], llm_rerank=True, shortlist_cap=1, score_threshold=0.35
        ),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="cap",
        db_path=tmp_path / "app.db",
        rerank_client=client,
    )
    assert client.seen_keys == ["linkedin:top"]
    by_id = {c.job_id: c for c in result.candidates}
    assert by_id["top"].llm_keep is True
    assert by_id["overflow"].prefilter_rank is None
    assert by_id["overflow"].llm_keep is None
    assert by_id["junk"].drop_reason == "title_mismatch"
    assert by_id["junk"].llm_keep is None


def test_rerank_failure_falls_back_and_keeps_the_run(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    adapter = FakeAdapter({"product designer": [_job("keep", "product")]})
    result = run_search(
        settings=_settings(sites=["linkedin"], llm_rerank=True),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="fallback",
        db_path=tmp_path / "app.db",
        rerank_client=_RecordingRerank(error=RuntimeError("429")),
    )
    assert result.summary.failed_reason is None
    assert result.summary.shortlisted == 1
    assert result.summary.llm_kept is None
    assert result.shortlist[0].llm_keep is None
    assert result.shortlist[0].prefilter_rank == 1
    assert result.llm_error == "429"
    assert (result.output_dir / "candidates.json").exists()


def test_llm_rerank_skipped_when_every_job_already_seen(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    db_path = tmp_path / "app.db"
    adapter = FakeAdapter({"product designer": [_job("keep", "product")]})
    run_search(
        settings=_settings(sites=["linkedin"]),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="one",
        db_path=db_path,
    )
    second = run_search(
        settings=_settings(sites=["linkedin"], llm_rerank=True),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="two",
        db_path=db_path,
        rerank_client=_RecordingRerank(items=[]),
    )
    assert second.summary.shortlisted == 0
    assert second.llm_error is not None
    assert "already seen" in second.llm_error


def test_resume_excerpt_reaches_rerank(tmp_path):
    store = YamlBioStore(tmp_path / "bio.yaml")
    adapter = FakeAdapter({"product designer": [_job("keep", "product")]})
    client = _RecordingRerank()
    result = run_search(
        settings=_settings(sites=["linkedin"], llm_rerank=True),
        bio_store=store,
        adapter=adapter,
        keywords=["product designer"],
        output_root=tmp_path / "runs",
        run_id="resume",
        db_path=tmp_path / "app.db",
        rerank_client=client,
        resume_excerpt="UX + game design, MI student.",
    )
    import json

    meta = json.loads((result.output_dir / "summary.json").read_text(encoding="utf-8"))
    assert meta["source"] == "resume_query"


