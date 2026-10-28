"""Draft management/catalog/CLI regressions; not executed in this development round."""

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from w_agent.knowledge_management import LocalKnowledgeRequest, manage_local_knowledge
from w_agent.knowledge_sqlite import KnowledgeStoreError, SQLiteKnowledgeSnapshotStore


def import_request(tmp_path, **overrides):
    options = dict(action="import", database=tmp_path / "knowledge.db", root=tmp_path,
                   paths=("faq.md",), namespace="manual", version="v1", confirm_read=True)
    options.update(overrides)
    return LocalKnowledgeRequest(**options)


@pytest.mark.asyncio
async def test_preview_then_save_catalog_and_pinned_search(tmp_path):
    (tmp_path / "faq.md").write_text("PRIVATE_BODY refund policy", encoding="utf-8")
    preview = await manage_local_knowledge(import_request(tmp_path))
    assert preview["state"] == "preview" and preview["chunks"] == 1
    assert "PRIVATE_BODY" not in json.dumps(preview)
    assert not (tmp_path / "knowledge.db").exists()
    saved = await manage_local_knowledge(import_request(tmp_path, confirm_create=True, confirm_write=True))
    assert saved["state"] == "saved" and saved["digest"] == preview["digest"]
    assert saved["manifest_persisted"] is False
    database = tmp_path / "knowledge.db"
    catalog = await manage_local_knowledge(LocalKnowledgeRequest("list", database, confirm_read=True))
    assert catalog["body_integrity_verified"] is False
    assert catalog["versions"][0]["digest"] == saved["digest"]
    request = dict(action="search", database=database, namespace="manual", version="v1",
                   query="refund", confirm_read=True)
    metadata = await manage_local_knowledge(LocalKnowledgeRequest(**request))
    assert metadata["body_integrity_verified"] is True
    assert len(metadata["matches"]) == 1 and "text" not in metadata["matches"][0]
    disclosed = await manage_local_knowledge(LocalKnowledgeRequest(**request, include_text=True))
    assert disclosed["matches"][0]["text"] == "PRIVATE_BODY refund policy"
    request["version"] = "missing"
    with pytest.raises(KnowledgeStoreError, match="knowledge-version-not-found"):
        await manage_local_knowledge(LocalKnowledgeRequest(**request))


@pytest.mark.parametrize("overrides", [
    {"confirm_read": False}, {"confirm_read": 1}, {"confirm_write": 1},
    {"confirm_create": True}, {"namespace": ""}, {"version": "v\n"},
    {"chunk_bytes": 3}, {"include_text": True}, {"paths": ()},
])
def test_preflight_without_any_files(tmp_path, overrides):
    with pytest.raises(ValueError):
        import_request(tmp_path, **overrides)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("options", [
    {"action": "list", "confirm_write": True},
    {"action": "list", "include_text": True},
    {"action": "list", "version": "v1"},
    {"action": "search", "namespace": "n", "version": "v", "query": "q", "limit": True},
    {"action": "search", "namespace": "n", "version": "v", "query": " "},
])
def test_read_only_actions_reject_unrelated_options(tmp_path, options):
    with pytest.raises(ValueError):
        LocalKnowledgeRequest(database=tmp_path / "missing.db", confirm_read=True, **options)


@pytest.mark.asyncio
async def test_append_only_and_catalog_does_not_validate_body(tmp_path):
    path = tmp_path / "faq.md"
    path.write_text("first", encoding="utf-8")
    request = import_request(tmp_path, confirm_create=True, confirm_write=True)
    await manage_local_knowledge(request)
    await manage_local_knowledge(request)  # Identical content is idempotent.
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(KnowledgeStoreError, match="knowledge-version-conflict"):
        await manage_local_knowledge(request)
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "knowledge.db")
    assert await store.list_snapshots("absent") == ()
    db = sqlite3.connect(tmp_path / "knowledge.db")
    try:
        db.execute("UPDATE knowledge_snapshots SET payload = '[]'")
        db.commit()
    finally:
        db.close()
    assert (await store.list_snapshots())[0].payload_bytes == 2
    with pytest.raises(KnowledgeStoreError):
        await store.load("manual", "v1")


@pytest.mark.asyncio
async def test_read_does_not_create_database(tmp_path):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "missing.db")
    with pytest.raises(KnowledgeStoreError):
        await store.list_snapshots()
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.asyncio
async def test_creation_then_save_failure_is_not_reported_as_no_write(tmp_path, monkeypatch):
    (tmp_path / "faq.md").write_text("faq", encoding="utf-8")

    async def rejected(self, snapshot, *, confirm_write=False):
        raise KnowledgeStoreError("knowledge-store-capacity-exceeded")

    monkeypatch.setattr(SQLiteKnowledgeSnapshotStore, "save", rejected)
    with pytest.raises(KnowledgeStoreError) as error:
        await manage_local_knowledge(import_request(tmp_path, confirm_write=True, confirm_create=True))
    assert error.value.may_have_written is True
    assert (tmp_path / "knowledge.db").exists()


@pytest.mark.asyncio
async def test_catalog_limit_and_invalid_metadata_are_errors_not_truncation(tmp_path):
    store = SQLiteKnowledgeSnapshotStore(tmp_path / "knowledge.db")
    await store.initialize(confirm_create=True)
    db = sqlite3.connect(tmp_path / "knowledge.db")
    try:
        db.executemany("INSERT INTO knowledge_snapshots VALUES (?, ?, ?, ?)",
                       (("n", str(index), "a" * 64, "[]") for index in range(4097)))
        db.commit()
        with pytest.raises(KnowledgeStoreError, match="knowledge-catalog-limit-exceeded"):
            await store.list_snapshots()
        db.execute("DELETE FROM knowledge_snapshots")
        db.execute("INSERT INTO knowledge_snapshots VALUES (?, ?, ?, ?)", ("n", "v", "bad", "[]"))
        db.commit()
        with pytest.raises(KnowledgeStoreError, match="knowledge-catalog-read-failed"):
            await store.list_snapshots()
    finally:
        db.close()


def test_cli_requires_confirmation_before_service(tmp_path, monkeypatch):
    import w_agent.knowledge_cli as adapter
    from w_agent.cli import app

    async def forbidden(request):
        pytest.fail("unconfirmed service call")

    monkeypatch.setattr(adapter, "manage_local_knowledge", forbidden)
    result = CliRunner().invoke(app, ["knowledge-list", "--database", str(tmp_path / "missing.db")])
    assert result.exit_code == 2
    assert not (tmp_path / "missing.db").exists()


def test_cli_preview_is_json_and_does_not_create_database(tmp_path):
    from w_agent.cli import app

    (tmp_path / "faq.md").write_text("SECRET", encoding="utf-8")
    result = CliRunner().invoke(app, [
        "knowledge-import", "--database", str(tmp_path / "knowledge.db"),
        "--root", str(tmp_path), "--path", "faq.md", "--namespace", "manual",
        "--version", "v1", "--confirm-read",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "preview"
    assert "SECRET" not in result.output and not (tmp_path / "knowledge.db").exists()
