import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
from dataclasses import replace

import pytest
import typer
from typer.testing import CliRunner

from w_agent.knowledge_archive_cli import register_knowledge_archive_commands
from w_agent.knowledge_archive_management import (
    KnowledgeArchiveCreateRequest, KnowledgeArchiveExportRequest, KnowledgeArchiveInspectRequest,
    KnowledgeArchivePreviewRequest, archive_local_knowledge_sources, export_local_knowledge_blob,
    inspect_local_knowledge_archive, preview_local_knowledge_archive,
)
from w_agent.knowledge_archives import KnowledgeArchiveError, KnowledgeArchiveReceipt, KnowledgeRawBlob, SQLiteKnowledgeRawArchive
from w_agent.knowledge_files import LocalTextKnowledgeImporter
from w_agent.knowledge_import_store import SQLiteKnowledgeImportStore
from w_agent.knowledge_provenance import prepare_traced_knowledge_import


async def prepare(tmp_path):
    source = tmp_path / "private-root"
    source.mkdir()
    (source / "private-name.md").write_bytes(b"private original\r\n")
    imported = await LocalTextKnowledgeImporter(source).load(("private-name.md",), confirm_read=True)
    trace = prepare_traced_knowledge_import("private-namespace", "v1", imported)
    store = SQLiteKnowledgeImportStore(tmp_path / "traces.db")
    await store.initialize(confirm_create=True)
    await store.save(trace, confirm_write=True)
    request = KnowledgeArchiveCreateRequest(
        store.database_path, tmp_path / "raw.db", source, "private-namespace", "v1", trace.digest,
        confirm_read=True, confirm_sources=True, confirm_write=True, confirm_create=True,
    )
    return request, trace


def export_request(tmp_path, request, summary):
    return KnowledgeArchiveExportRequest(request.archive_database, request.expected_trace_digest,
        summary["receipt_digest"], summary["blob_digests"][0], tmp_path / "export.bin",
        confirm_read=True, confirm_export=True, confirm_path=True)


@pytest.mark.asyncio
async def test_management_real_sqlite_roundtrip_without_body_path_disclosure(tmp_path):
    request, trace = await prepare(tmp_path)
    preview = await preview_local_knowledge_archive(KnowledgeArchivePreviewRequest(
        request.trace_database, request.namespace, request.version, confirm_read=True))
    assert preview == {"trace_digest": trace.digest, "source_count": 1, "blob_count": 1,
                       "raw_bytes": 18, "chunk_count": 1, "source_files_read": False}
    assert not request.archive_database.exists()
    saved = await archive_local_knowledge_sources(request)
    summary = await inspect_local_knowledge_archive(KnowledgeArchiveInspectRequest(
        request.archive_database, trace.digest, confirm_read=True))
    assert summary["verified"] and summary["receipt_digest"] == saved["receipt_digest"]
    output = export_request(tmp_path, request, summary)
    assert (await export_local_knowledge_blob(output))["exported"]
    assert output.destination.read_bytes() == b"private original\r\n"
    for text in (json.dumps(preview), json.dumps(saved), json.dumps(summary), repr(request), repr(output)):
        for secret in ("private original", "private-name", "private-root", "private-namespace", str(tmp_path)):
            assert secret not in text


@pytest.mark.parametrize("operation,flag", [
    ("preview", "confirm_read"), ("save", "confirm_read"), ("save", "confirm_sources"),
    ("save", "confirm_write"), ("inspect", "confirm_read"), ("export", "confirm_read"),
    ("export", "confirm_export"), ("export", "confirm_path"),
])
def test_missing_confirmation_precedes_all_io(tmp_path, monkeypatch, operation, flag):
    def forbidden(*args, **kwargs):
        pytest.fail("no filesystem/SQLite access before all confirmations")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(type(tmp_path), "lstat", forbidden)
    monkeypatch.setattr(type(tmp_path), "stat", forbidden)
    requests = {
        "preview": (KnowledgeArchivePreviewRequest, dict(trace_database=tmp_path / "trace.db", namespace="n", version="v", confirm_read=True)),
        "save": (KnowledgeArchiveCreateRequest, dict(trace_database=tmp_path / "trace.db", archive_database=tmp_path / "raw.db", root=tmp_path,
                    namespace="n", version="v", expected_trace_digest="a" * 64, confirm_read=True, confirm_sources=True, confirm_write=True)),
        "inspect": (KnowledgeArchiveInspectRequest, dict(archive_database=tmp_path / "raw.db", trace_digest="a" * 64, confirm_read=True)),
        "export": (KnowledgeArchiveExportRequest, dict(archive_database=tmp_path / "raw.db", trace_digest="a" * 64,
                    expected_receipt_digest="b" * 64, blob_digest="c" * 64, destination=tmp_path / "out", confirm_read=True, confirm_export=True, confirm_path=True)),
    }
    kind, options = requests[operation]
    options[flag] = False
    with pytest.raises(KnowledgeArchiveError, match="not-authorized"):
        kind(**options)


@pytest.mark.asyncio
async def test_wrong_approval_or_source_drift_never_creates_archive(tmp_path, monkeypatch):
    request, _ = await prepare(tmp_path)
    import w_agent.knowledge_archives as archive_module
    original = archive_module._read_sources
    monkeypatch.setattr(archive_module, "_read_sources", lambda *args: pytest.fail("approval must precede source reading"))
    with pytest.raises(KnowledgeArchiveError, match="approval-mismatch"):
        await archive_local_knowledge_sources(replace(request, expected_trace_digest="0" * 64))
    assert not request.archive_database.exists()
    monkeypatch.setattr(archive_module, "_read_sources", original)
    (request.root / "private-name.md").write_bytes(b"changed")
    with pytest.raises(KnowledgeArchiveError, match="source-changed"):
        await archive_local_knowledge_sources(request)
    assert not request.archive_database.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("hardlink", [False, True])
async def test_same_database_or_hardlink_alias_rejected_unchanged(tmp_path, hardlink):
    request, _ = await prepare(tmp_path)
    target = request.trace_database
    if hardlink:
        target = tmp_path / "alias.db"
        os.link(request.trace_database, target)
    before = request.trace_database.read_bytes()
    with pytest.raises(KnowledgeArchiveError, match="must-differ"):
        await archive_local_knowledge_sources(replace(request, archive_database=target))
    assert request.trace_database.read_bytes() == before


@pytest.mark.asyncio
async def test_preview_does_not_require_original_source_files(tmp_path):
    request, trace = await prepare(tmp_path)
    (request.root / "private-name.md").unlink()
    summary = await preview_local_knowledge_archive(KnowledgeArchivePreviewRequest(
        request.trace_database, request.namespace, request.version, confirm_read=True))
    assert summary["trace_digest"] == trace.digest


@pytest.mark.asyncio
async def test_inspect_missing_database_does_not_create(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(KnowledgeArchiveError):
        await inspect_local_knowledge_archive(KnowledgeArchiveInspectRequest(path, "a" * 64, confirm_read=True))
    assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["existing", "archive", "trace", "wrong-receipt", "foreign-blob"])
async def test_export_rejects_unapproved_or_existing_target(tmp_path, kind):
    request, _ = await prepare(tmp_path)
    summary = await archive_local_knowledge_sources(request)
    export = export_request(tmp_path, request, summary)
    if kind == "existing":
        export.destination.write_bytes(b"keep")
    elif kind in ("archive", "trace"):
        export = replace(export, destination=request.archive_database if kind == "archive" else request.trace_database)
    elif kind == "wrong-receipt":
        export = replace(export, expected_receipt_digest="0" * 64)
    else:
        export = replace(export, blob_digest="0" * 64)
    before = export.destination.read_bytes() if export.destination.exists() else None
    with pytest.raises(KnowledgeArchiveError):
        await export_local_knowledge_blob(export)
    assert (export.destination.read_bytes() if export.destination.exists() else None) == before


@pytest.mark.asyncio
async def test_export_partial_write_failure_removes_only_owned_file(tmp_path, monkeypatch):
    request, _ = await prepare(tmp_path)
    summary = await archive_local_knowledge_sources(request)
    export = export_request(tmp_path, request, summary)
    def fail(_fd):
        raise OSError("private failure path")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(KnowledgeArchiveError, match="partial-file-may-remain") as error:
        await export_local_knowledge_blob(export)
    assert "private failure" not in str(error.value)
    assert not export.destination.exists()


@pytest.mark.asyncio
async def test_export_cleanup_preserves_concurrently_replaced_file(tmp_path, monkeypatch):
    request, _ = await prepare(tmp_path)
    summary = await archive_local_knowledge_sources(request)
    export = export_request(tmp_path, request, summary)
    # At fstat time the owned file identity is retained; replacement occurs after close.
    original_close = os.close
    replaced = False
    def swap(fd):
        nonlocal replaced
        original_close(fd)
        if not replaced:
            replaced = True
            export.destination.rename(tmp_path / "owned-partial")
            export.destination.write_bytes(b"user replacement")
    monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("failed")))
    monkeypatch.setattr(os, "close", swap)
    with pytest.raises(KnowledgeArchiveError):
        await export_local_knowledge_blob(export)
    assert export.destination.read_bytes() == b"user replacement"


@pytest.mark.asyncio
async def test_corrupted_blob_fails_before_export(tmp_path):
    request, _ = await prepare(tmp_path)
    summary = await archive_local_knowledge_sources(request)
    export = export_request(tmp_path, request, summary)
    with sqlite3.connect(request.archive_database) as db:
        db.execute("UPDATE archive_blobs SET payload = ?", (b"tampered",))
    with pytest.raises(Exception):
        await export_local_knowledge_blob(export)
    assert not export.destination.exists()


@pytest.mark.asyncio
async def test_inert_binary_export_is_byte_exact(tmp_path):
    archive = SQLiteKnowledgeRawArchive(tmp_path / "raw.db")
    await archive.initialize(confirm_create=True)
    content = b"\x00MZ macro-script bytes are not launched\xff"
    blob = KnowledgeRawBlob(hashlib.sha256(content).hexdigest(), content)
    receipt = KnowledgeArchiveReceipt("a" * 64, (blob.digest,))
    await archive.save(receipt, (blob,), confirm_write=True)
    export = KnowledgeArchiveExportRequest(archive.database_path, receipt.trace_digest, receipt.digest,
        blob.digest, tmp_path / "inert.bin", confirm_read=True, confirm_export=True, confirm_path=True)
    assert (await export_local_knowledge_blob(export))["bytes"] == len(content)
    assert export.destination.read_bytes() == content


@pytest.mark.asyncio
async def test_export_rejects_linked_parent_and_leaf(tmp_path):
    request, _ = await prepare(tmp_path)
    summary = await archive_local_knowledge_sources(request)
    export = export_request(tmp_path, request, summary)
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "linked"
    junction = False
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Windows junction creation needs no symlink privilege. Both absolute
        # paths are exact children of this test's temporary workspace.
        assert link.parent == target.parent == tmp_path
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, check=False)
        assert result.returncode == 0
        junction = True
    try:
        with pytest.raises(KnowledgeArchiveError):
            await export_local_knowledge_blob(replace(export, destination=link / "new.bin"))
        assert not (target / "new.bin").exists()
        # The junction itself also cannot be selected as an output file.
        with pytest.raises(KnowledgeArchiveError):
            await export_local_knowledge_blob(replace(export, destination=link))
    finally:
        if junction:
            os.rmdir(link)  # Removes the junction itself, never its target.
        else:
            link.unlink()
    assert target.is_dir()


@pytest.mark.asyncio
async def test_export_cleanup_failure_retains_partial_and_fixed_error(tmp_path, monkeypatch):
    request, _ = await prepare(tmp_path)
    summary = await archive_local_knowledge_sources(request)
    export = export_request(tmp_path, request, summary)
    def fail(*args, **kwargs):
        raise OSError("sensitive exception")
    monkeypatch.setattr(os, "fsync", fail)
    monkeypatch.setattr(type(tmp_path), "unlink", fail)
    with pytest.raises(KnowledgeArchiveError, match="partial-file-may-remain") as error:
        await export_local_knowledge_blob(export)
    assert "sensitive" not in str(error.value)
    assert export.destination.exists()


@pytest.mark.asyncio
async def test_missing_create_authorization_does_not_create_database(tmp_path):
    request, _ = await prepare(tmp_path)
    with pytest.raises(KnowledgeArchiveError):
        await archive_local_knowledge_sources(replace(request, confirm_create=False))
    assert not request.archive_database.exists()


def test_cli_full_chain_real_sqlite(tmp_path):
    request, _ = asyncio.run(prepare(tmp_path))
    app = typer.Typer()
    register_knowledge_archive_commands(app)
    runner = CliRunner()
    common = ["--trace-database", str(request.trace_database), "--namespace", request.namespace, "--version", request.version, "--confirm-read"]
    preview = runner.invoke(app, ["knowledge-archive", "preview", *common])
    assert preview.exit_code == 0, preview.output
    digest = json.loads(preview.output)["trace_digest"]
    save = runner.invoke(app, ["knowledge-archive", "save", *common, "--archive-database", str(request.archive_database),
        "--root", str(request.root), "--expected-trace-digest", digest, "--confirm-sources", "--confirm-write", "--confirm-create"])
    assert save.exit_code == 0, save.output
    inspect = runner.invoke(app, ["knowledge-archive", "inspect", "--archive-database", str(request.archive_database),
        "--trace-digest", digest, "--confirm-read"])
    assert inspect.exit_code == 0, inspect.output
    summary = json.loads(inspect.output)
    output = tmp_path / "cli-output.bin"
    export = runner.invoke(app, ["knowledge-archive", "export", "--archive-database", str(request.archive_database),
        "--trace-digest", digest, "--expected-receipt-digest", summary["receipt_digest"], "--blob-digest", summary["blob_digests"][0],
        "--destination", str(output), "--confirm-read", "--confirm-export", "--confirm-path"])
    assert export.exit_code == 0, export.output
    assert output.read_bytes() == b"private original\r\n"
    for result in (preview, save, inspect, export):
        assert "private" not in result.output
        assert str(tmp_path) not in result.output


def test_cli_missing_authority_and_help(tmp_path):
    app = typer.Typer()
    register_knowledge_archive_commands(app)
    runner = CliRunner()
    for command in ("preview", "save", "inspect", "export"):
        assert runner.invoke(app, ["knowledge-archive", command, "--help"]).exit_code == 0
    result = runner.invoke(app, ["knowledge-archive", "inspect", "--archive-database", str(tmp_path / "private.db"), "--trace-digest", "a" * 64])
    assert result.exit_code == 2
    assert "private.db" not in result.output
    assert not (tmp_path / "private.db").exists()
