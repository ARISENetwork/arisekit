"""Shared fields and model-call plumbing for judge-backed scorers."""

from __future__ import annotations

import logging
from typing import ClassVar

from arisekit.client import ModelCall, ModelClient, resolve_client
from arisekit.scorer import BaseScorer
from arisekit.types import BenchmarkItem

log = logging.getLogger("arisekit.judges")


class ModelJudge(BaseScorer):
    """A scorer that asks one judge model about each response. Subclasses build the prompt, parse the reply, and
    reduce the trials to metrics."""

    # Judge calls are identified as "<call_id_prefix>:<item id>".
    call_id_prefix: ClassVar[str] = "judge"
    # Log a warning when a judge call fails; otherwise the failed call is skipped silently.
    log_failures: ClassVar[bool] = False

    def __init__(
        self,
        *,
        judge_model: str,
        client: ModelClient | None = None,
        temperature: float | None = 0.0,
    ):
        self.judge_model = judge_model
        self.temperature = temperature
        self._client = client or resolve_client(judge_model)

    def _ask(self, item: BenchmarkItem, prompt: str) -> str | None:
        """The judge's reply text for one prompt about `item`, or None when the call fails."""
        call = ModelCall(item=BenchmarkItem(id=f"{self.call_id_prefix}:{item.id}", prompt=prompt),
                         temperature=self.temperature)
        try:
            result = self._client(call)
        except Exception as exc:  # noqa: BLE001
            if self.log_failures:
                log.warning("judge %s failed on %s: %s", self.judge_model, item.id, exc)
            return None
        return result.text
