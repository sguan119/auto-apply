"""tests.test_bio_store —— core.bio.store.YamlBioStore 的读写往返测试。"""

from __future__ import annotations

import pytest
import yaml

from core.bio.store import YamlBioStore


class TestYamlBioStore:
    def test_read_missing_file_returns_none(self, tmp_path):
        store = YamlBioStore(tmp_path / "bio.yaml")
        assert store.read_path("preferences.visa_sponsorship_needed") is None

    def test_write_then_read_round_trip(self, tmp_path):
        store = YamlBioStore(tmp_path / "bio.yaml")
        store.write_path("preferences.visa_sponsorship_needed", "No")
        assert store.read_path("preferences.visa_sponsorship_needed") == "No"

    def test_write_creates_intermediate_levels(self, tmp_path):
        path = tmp_path / "bio.yaml"
        store = YamlBioStore(path)
        store.write_path("a.b.c", "deep value")

        assert store.read_path("a.b.c") == "deep value"
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        assert raw["a"]["b"]["c"] == "deep value"

    def test_read_missing_nested_path_returns_none(self, tmp_path):
        store = YamlBioStore(tmp_path / "bio.yaml")
        store.write_path("a.b", "x")
        assert store.read_path("a.z") is None
        assert store.read_path("a.b.c") is None  # b 是字符串不是 dict，不能再往下走

    def test_file_created_lazily(self, tmp_path):
        path = tmp_path / "nested" / "bio.yaml"
        store = YamlBioStore(path)
        assert not path.exists()
        store.write_path("x", "1")
        assert path.exists()

    def test_existing_content_preserved_on_write(self, tmp_path):
        path = tmp_path / "bio.yaml"
        path.write_text(
            yaml.safe_dump({"personal": {"name": "Alice"}}, allow_unicode=True),
            encoding="utf-8",
        )
        store = YamlBioStore(path)
        store.write_path("preferences.relocate", "Yes")

        assert store.read_path("personal.name") == "Alice"
        assert store.read_path("preferences.relocate") == "Yes"

    def test_write_with_question_stores_note_without_polluting_value(self, tmp_path):
        path = tmp_path / "bio.yaml"
        store = YamlBioStore(path)
        store.write_path(
            "preferences.visa_sponsorship_needed",
            "No",
            question="Do you require visa sponsorship?",
        )

        # 正文字段值不受影响
        assert store.read_path("preferences.visa_sponsorship_needed") == "No"
        # 问题备注进独立保留键（扁平 field_path -> question），不嵌入正文结构
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        assert raw["_field_notes"]["preferences.visa_sponsorship_needed"] == (
            "Do you require visa sponsorship?"
        )

    def test_overwrite_existing_value(self, tmp_path):
        store = YamlBioStore(tmp_path / "bio.yaml")
        store.write_path("preferences.relocate", "No")
        store.write_path("preferences.relocate", "Yes")
        assert store.read_path("preferences.relocate") == "Yes"

    def test_reserved_field_notes_key_rejected(self, tmp_path):
        # 字段路径撞上内部保留键 _field_notes 必须显式报错，绝不静默污染数据树。
        path = tmp_path / "bio.yaml"
        store = YamlBioStore(path)
        store.write_path("personal.name", "Alice")

        with pytest.raises(ValueError):
            store.write_path("_field_notes", "boom")
        with pytest.raises(ValueError):
            store.write_path("_field_notes.preferences.relocate", "boom")

        # 既有正文完好无损，文件未被破坏。
        assert store.read_path("personal.name") == "Alice"

    def test_multiline_value_round_trips_readably(self, tmp_path):
        # 决策九：bio.yaml 选 YAML 正是为多行文本（经历描述）友好，验证不被压成一行/损坏。
        path = tmp_path / "bio.yaml"
        store = YamlBioStore(path)
        multiline = "Line one\nLine two\nLine three"
        store.write_path("experience.summary", multiline)

        assert store.read_path("experience.summary") == multiline
        # 换行在磁盘上真的以多行形式存在（YAML 块/引号标量），不是转义成 \n 的单行。
        raw = path.read_text(encoding="utf-8")
        assert "Line two" in raw and raw.count("\n") >= 3
