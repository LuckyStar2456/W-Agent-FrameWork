"""Registered CLI path from overlapping v2 trace through byte-identical raw export."""

import asyncio
import hashlib
import json

from typer.testing import CliRunner

from w_agent.cli import app
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore


def test_structure_trace_archive_export_full_offline_cli_path(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    original = ("PRIVATE_SOURCE\n\n第一段说明。第二句话包含🙂。\n\n" * 8).encode("utf-8")
    (source / "manual.txt").write_bytes(original)
    trace_path, archive_path = tmp_path / "trace.sqlite", tmp_path / "raw.sqlite"
    runner = CliRunner()

    def invoke(args):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "PRIVATE_SOURCE" not in result.output and str(tmp_path) not in result.output
        return json.loads(result.output)

    import_args = ["knowledge-sync-import", "--trace-database", str(trace_path),
        "--root", str(source), "--namespace", "manual", "--version", "one",
        "--path", "manual.txt", "--splitter", "structure", "--chunk-bytes", "96",
        "--overlap-chars", "4", "--confirm-read"]
    preview = invoke(import_args)
    assert not trace_path.exists() and preview["chunks"] > 1
    saved = invoke([*import_args, "--expected-preview-digest", preview["preview_digest"],
                    "--confirm-record", "--confirm-create"])
    assert saved["trace_digest"] == preview["trace_digest"]
    trace = asyncio.run(SQLiteKnowledgeImportStore(trace_path).load("manual", "one"))
    assert json.loads(trace.to_json())["format"] == "wagent-traced-knowledge-import-v2"
    assert any(right.char_start < left.char_end for left, right in zip(trace.origins, trace.origins[1:]))

    archive_preview = invoke(["knowledge-archive", "preview", "--trace-database", str(trace_path),
                              "--namespace", "manual", "--version", "one", "--confirm-read"])
    assert archive_preview["trace_digest"] == trace.digest and not archive_path.exists()
    saved_archive = invoke(["knowledge-archive", "save", "--trace-database", str(trace_path),
        "--archive-database", str(archive_path), "--root", str(source), "--namespace", "manual",
        "--version", "one", "--expected-trace-digest", archive_preview["trace_digest"],
        "--confirm-read", "--confirm-sources", "--confirm-write", "--confirm-create"])
    inspected = invoke(["knowledge-archive", "inspect", "--archive-database", str(archive_path),
                         "--trace-digest", trace.digest, "--confirm-read"])
    digest = hashlib.sha256(original).hexdigest()
    assert inspected["blob_digests"] == [digest]
    assert inspected["receipt_digest"] == saved_archive["receipt_digest"]

    destination = tmp_path / "raw-export.bin"
    export_args = ["knowledge-archive", "export", "--archive-database", str(archive_path),
        "--trace-digest", trace.digest, "--expected-receipt-digest", inspected["receipt_digest"],
        "--blob-digest", digest, "--destination", str(destination), "--confirm-read",
        "--confirm-export", "--confirm-path"]
    exported = invoke(export_args)
    assert exported["bytes"] == len(original) and destination.read_bytes() == original
    before = destination.read_bytes(), archive_path.read_bytes(), trace_path.read_bytes()
    refused = runner.invoke(app, export_args)
    assert refused.exit_code == 2
    assert (destination.read_bytes(), archive_path.read_bytes(), trace_path.read_bytes()) == before
