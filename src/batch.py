"""Concurrent batch verification.

Peak-season importers drop 200-300 applications at once (Janet's ask). We fan
the work out across a small thread pool — each label is one independent API
call — and report results as they complete so the UI can show live progress.
Concurrency is capped (config.BATCH_MAX_WORKERS) to stay under API rate limits.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional

from .config import BATCH_MAX_WORKERS
from .models import ApplicationData, VerificationReport
from .verification import verify_label


@dataclass
class BatchItem:
    """One row of a batch job: an application plus its label image."""

    name: str  # human-facing id, usually the image filename
    application: ApplicationData
    image_bytes: Optional[bytes]
    media_type: str = "image/png"


@dataclass
class BatchResult:
    name: str
    report: VerificationReport


def run_batch(
    items: list[BatchItem],
    provider,
    max_workers: int = BATCH_MAX_WORKERS,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> list[BatchResult]:
    """Verify every item concurrently. Results are returned in input order.

    `on_progress(done, total)` is called after each item completes so callers
    can drive a progress bar.
    """
    total = len(items)
    results: dict[int, BatchResult] = {}
    done = 0

    def _work(index: int, item: BatchItem) -> tuple[int, BatchResult]:
        if not item.image_bytes:
            from .models import OverallStatus

            report = VerificationReport(
                overall=OverallStatus.ERROR,
                error="No image was provided for this row.",
                model_used=getattr(provider, "name", ""),
                demo_mode=getattr(provider, "is_demo", False),
            )
        else:
            report = verify_label(
                item.application, item.image_bytes, item.media_type, provider, hint=item.name
            )
        return index, BatchResult(name=item.name, report=report)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = [pool.submit(_work, i, item) for i, item in enumerate(items)]
        for future in as_completed(futures):
            index, result = future.result()
            results[index] = result
            done += 1
            if on_progress:
                on_progress(done, total)

    return [results[i] for i in range(total)]
