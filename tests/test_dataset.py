import json
from pathlib import Path

from arisekit import BenchmarkItem, Dataset


def test_from_items_roundtrip():
    items = [
        BenchmarkItem(id="a", prompt="What is 2+2?", ground_truth="4"),
        BenchmarkItem(id="b", prompt="Capital of France?", ground_truth="Paris"),
    ]
    ds = Dataset.from_items(items, system_prompt="You are a tutor.")
    assert len(ds) == 2
    assert ds.system_prompt == "You are a tutor."
    assert ds[0].id == "a"
    assert list(iter(ds))[1].ground_truth == "Paris"


def test_from_jsonl_reads_back_what_we_wrote(tmp_path: Path):
    path = tmp_path / "items.jsonl"
    rows = [
        {"id": "1", "prompt": "Q1", "ground_truth": "A"},
        {"id": "2", "prompt": "Q2", "metadata": {"specialty": "cards"}},
    ]
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

    ds = Dataset.from_jsonl(path)
    assert len(ds) == 2
    assert ds[0].id == "1"
    assert ds[1].metadata == {"specialty": "cards"}


def test_from_jsonl_rejects_bad_json(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"1","prompt":"ok"}\nnot-json\n', encoding="utf-8")
    try:
        Dataset.from_jsonl(path)
    except ValueError as exc:
        assert "line 2" in str(exc) or "bad.jsonl:2" in str(exc)
    else:
        raise AssertionError("expected ValueError on malformed JSONL")


def test_limit_returns_truncated_dataset():
    items = [BenchmarkItem(id=str(i), prompt=f"Q{i}") for i in range(10)]
    ds = Dataset.from_items(items)
    short = ds.limit(3)
    assert len(short) == 3
    assert short[2].id == "2"
