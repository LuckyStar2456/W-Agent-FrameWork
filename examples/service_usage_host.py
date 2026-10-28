"""Editable local usage host; importing this module performs no I/O.

Create the parent directory and explicitly initialize both stores separately
after reviewing docs/service-usage-links.md. This factory never creates or
migrates databases. CLI callers independently authorize host code and recording.
"""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from w_agent.service_usage_links import SQLiteServiceUsageLinkStore
from w_agent.service_usage_runtime import LocalServiceUsageBinding
from w_agent.service_usage_sqlite import SQLiteServiceUsageLedger


@asynccontextmanager
async def usage_factory():
    """Borrow two existing local stores under an explicit host operation label.

    Reuse the same operation and link database when resuming a linked Run.
    An operation may cover multiple Runs; it is not a tenant or per-Run total.
    Files remain host-owned and unencrypted. Separate stores are not one atomic
    transaction; inspect any interrupted setup or write instead of replaying work.
    """
    operation = os.environ.get("WAGENT_USAGE_OPERATION")
    if not operation:
        raise ValueError("set an explicit WAGENT_USAGE_OPERATION opaque label")
    root = Path(os.environ.get("WAGENT_USAGE_ROOT", ".wagent")).absolute()
    yield {"local-usage": LocalServiceUsageBinding(
        SQLiteServiceUsageLedger(root / "service-usage.sqlite3"), operation,
        links=SQLiteServiceUsageLinkStore(root / "service-usage-links.sqlite3"),
    )}
