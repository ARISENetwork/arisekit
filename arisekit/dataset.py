"""Dataset loaders.

A Dataset is an iterable of BenchmarkItems plus an optional system
prompt that the runner stitches onto each item. Loaders are
constructors on the class; subclassing is reserved for custom sources
that need state (HF streaming, FHIR test beds, etc.).
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from arisekit.types import BenchmarkItem


class Dataset:
    """A sequence of BenchmarkItems with an optional system prompt."""

    def __init__(
        self,
        items: Iterable[BenchmarkItem],
        *,
        system_prompt: str | None = None,
        name: str | None = None,
    ):
        self._items: list[BenchmarkItem] = list(items)
        self.system_prompt = system_prompt
        self.name = name

    def __iter__(self) -> Iterator[BenchmarkItem]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, idx: int) -> BenchmarkItem:
        return self._items[idx]

    def limit(self, n: int) -> "Dataset":
        return Dataset(self._items[:n], system_prompt=self.system_prompt, name=self.name)

    # --- loaders -----------------------------------------------------

    @classmethod
    def from_items(
        cls,
        items: Iterable[BenchmarkItem | dict[str, Any]],
        *,
        system_prompt: str | None = None,
        name: str | None = None,
    ) -> "Dataset":
        normalized = [
            i if isinstance(i, BenchmarkItem) else BenchmarkItem.from_dict(i)
            for i in items
        ]
        return cls(normalized, system_prompt=system_prompt, name=name)

    @classmethod
    def from_jsonl(
        cls,
        path: str | Path,
        *,
        system_prompt: str | None = None,
        name: str | None = None,
    ) -> "Dataset":
        path = Path(path)
        items: list[BenchmarkItem] = []
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{path}:{line_no} is not valid JSON: {exc}"
                    ) from exc
                items.append(BenchmarkItem.from_dict(payload))
        return cls(items, system_prompt=system_prompt, name=name or path.stem)

    @classmethod
    def from_csv(
        cls,
        path: str | Path,
        *,
        id_col: str = "id",
        prompt_col: str = "prompt",
        ground_truth_col: str | None = "ground_truth",
        system_prompt: str | None = None,
        name: str | None = None,
    ) -> "Dataset":
        path = Path(path)
        items: list[BenchmarkItem] = []
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise ValueError(f"{path} has no header row")
            for idx, row in enumerate(reader):
                metadata = {
                    k: v
                    for k, v in row.items()
                    if k not in {id_col, prompt_col, ground_truth_col}
                }
                items.append(
                    BenchmarkItem(
                        id=str(row.get(id_col) or f"row-{idx}"),
                        prompt=row.get(prompt_col, ""),
                        metadata=metadata,
                        ground_truth=row.get(ground_truth_col) if ground_truth_col else None,
                    )
                )
        return cls(items, system_prompt=system_prompt, name=name or path.stem)

    @classmethod
    def from_hf(
        cls,
        repo_id: str,
        *,
        split: str = "test",
        prompt_col: str = "prompt",
        id_col: str | None = None,
        ground_truth_col: str | None = None,
        system_prompt: str | None = None,
        name: str | None = None,
    ) -> "Dataset":
        try:
            from datasets import load_dataset  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "from_hf requires the optional `hf` extra: pip install 'arisekit[hf]'"
            ) from exc
        ds = load_dataset(repo_id, split=split)
        items: list[BenchmarkItem] = []
        for idx, row in enumerate(ds):
            metadata = {
                k: v for k, v in row.items() if k not in {id_col, prompt_col, ground_truth_col}
            }
            items.append(
                BenchmarkItem(
                    id=str(row[id_col]) if id_col and id_col in row else f"hf-{idx}",
                    prompt=row[prompt_col],
                    metadata=metadata,
                    ground_truth=row.get(ground_truth_col) if ground_truth_col else None,
                )
            )
        return cls(items, system_prompt=system_prompt, name=name or repo_id)

    @classmethod
    def from_package(
        cls,
        pkg_or_path: Any,
        *,
        system_prompt: str | None = None,
    ) -> "Dataset":
        """Build a Dataset from a Benchmark Package (a directory or a
        loaded BenchmarkPackage). Cases carry the standard BenchmarkItem
        shape, so no reshaping is needed."""
        # Local import avoids a package <-> dataset import cycle
        # (arisekit.package imports Dataset).
        from arisekit.package import dataset_from_package

        return dataset_from_package(pkg_or_path, system_prompt=system_prompt)
