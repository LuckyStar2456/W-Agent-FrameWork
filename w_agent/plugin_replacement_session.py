"""Explicit, process-local replacement review shared by terminal interfaces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from w_agent.kernel.loading import PluginReference, import_plugin
from w_agent.kernel.plugins import PluginManager, PluginReplacementPlan


class PluginReplacementSession:
    """Bind source/config drift checks to a manager's one-shot replacement plan.

    This controller never discovers or installs code, drains runs, or owns the
    supplied manager. Import and quiescence are independent caller assertions.
    """

    def __init__(self, manager: PluginManager) -> None:
        self.manager = manager
        self._path: Path | None = None
        self._digest: str | None = None
        self._reference: PluginReference | None = None
        self._plan: PluginReplacementPlan | None = None

    @property
    def plan(self) -> PluginReplacementPlan | None:
        return self._plan

    def cancel(self) -> None:
        if self._plan is not None:
            self.manager.discard_replacement(self._plan)
        self._path = None
        self._digest = None
        self._reference = None
        self._plan = None

    def inspect(self, source: str | Path) -> dict[str, Any]:
        """Read exactly one enabled reference; do not import code or expose config."""
        self.cancel()
        path = Path(source).resolve()
        with path.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("replacement configuration exceeds 1 MiB")
        data = yaml.safe_load(raw.decode("utf-8"))
        if not isinstance(data, dict) or set(data) != {"plugins"}:
            raise ValueError("replacement configuration requires only a plugins list")
        rows = data["plugins"]
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError("replacement needs exactly one plugin reference")
        row = rows[0]
        if set(row) - {"entry", "config", "enabled"}:
            raise ValueError("unknown replacement reference fields")
        if not isinstance(row.get("entry"), str) or row.get("enabled", True) is not True:
            raise ValueError("replacement entry must be enabled and a string")
        config = row.get("config", {})
        if not isinstance(config, dict) or any(not isinstance(key, str) for key in config):
            raise ValueError("replacement config requires string keys")
        # Keep a detached, JSON-compatible configuration, never secret-bearing preview values.
        config = json.loads(json.dumps(config, allow_nan=False))
        reference = PluginReference(row["entry"], config)
        self._path, self._reference = path, reference
        self._digest = hashlib.sha256(raw).hexdigest()
        return {
            "scope": "current_process_only", "entry": reference.entry,
            "config_keys": sorted(config), "source_digest": self._digest,
            "import_confirmation": f"IMPORT REPLACEMENT {self._digest}",
            "code_imported": False,
        }

    def _check_source(self) -> PluginReference:
        if self._path is None or self._reference is None or self._digest is None:
            raise ValueError("inspect the replacement configuration first")
        with self._path.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576 or hashlib.sha256(raw).hexdigest() != self._digest:
            self.cancel()
            raise ValueError("replacement configuration changed; inspect again")
        return self._reference

    async def prepare(self, *, import_confirmation: str) -> dict[str, Any]:
        """Import trusted code only after the exact reviewed source is authorized."""
        reference = self._check_source()
        if import_confirmation != f"IMPORT REPLACEMENT {self._digest}":
            raise ValueError("exact import confirmation required")
        if self._plan is not None:
            self.manager.discard_replacement(self._plan)
            self._plan = None
        try:
            candidate = import_plugin(reference)
            self._check_source()
            self._plan = await self.manager.plan_replacement(candidate)
        except BaseException:
            self.cancel()
            raise
        plan = self._plan
        return {
            "scope": "current_process_only", "plan_id": plan.plan_id,
            "name": plan.previous.name, "previous_version": plan.previous.version,
            "replacement_version": plan.replacement.version,
            "unload_order": list(plan.unload_order),
            "requires": [
                {"capability": item.capability, "name": item.name, "version": item.version}
                for item in plan.replacement.requires
            ],
            "provides": [
                {"capability": item.capability, "name": item.name, "version": item.version}
                for item in plan.replacement.provides
            ],
            "replace_confirmation": f"REPLACE {plan.plan_id}",
            "quiescent_confirmation": f"QUIESCENT {plan.plan_id}",
            "consumers_restarted": False,
        }

    async def execute(
        self, *, replace_confirmation: str, quiescent_confirmation: str,
        host_busy: bool = False, blocked_names: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """Execute once; every execution attempt discards the review on completion."""
        try:
            reference = self._check_source()
            plan = self._plan
            if plan is None:
                raise ValueError("prepare a replacement plan first")
            if host_busy:
                raise ValueError("host has active work; stop users before replacement")
            if blocked_names.intersection(plan.unload_order):
                raise ValueError("installed package batches require a fresh-process update")
            if replace_confirmation != f"REPLACE {plan.plan_id}":
                raise ValueError("exact replacement confirmation required")
            if quiescent_confirmation != f"QUIESCENT {plan.plan_id}":
                raise ValueError("exact host quiescence confirmation required")
            handle = await self.manager.replace(
                plan, expected_plan_id=plan.plan_id, host_quiescent=True,
                config=reference.config,
            )
            return {
                "scope": "current_process_only", "name": handle.name,
                "version": plan.replacement.version, "state": handle.state.value,
                "stopped_consumers": list(plan.unload_order[:-1]),
                "project_updated": False, "other_processes_updated": False,
            }
        finally:
            self.cancel()
