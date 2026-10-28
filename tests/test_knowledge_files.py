"""Draft local knowledge-import regressions; not executed during development."""

import asyncio
import hashlib
import json
import os
import stat
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from w_agent import (
    KnowledgeFileImportError, KnowledgeTextImport, LocalTextKnowledgeImporter,
    Utf8KnowledgeFileParser, Utf8KnowledgeTextSplitter, prepare_knowledge_snapshot,
)
from w_agent.knowledge_files import _reject_link


def test_default_parser_strips_only_initial_bom_and_preserves_line_endings():
    parser = Utf8KnowledgeFileParser()
    assert parser.parse(b"\xef\xbb\xbfA\r\nB\n", relative_path="a.txt") == "A\r\nB\n"
    assert parser.parse(b"A\xef\xbb\xbfB", relative_path="a.txt") == "A\ufeffB"
    assert parser.parse(b"", relative_path="a.txt") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", [False, None, 1, "yes"])
async def test_construction_and_denied_reads_do_not_touch_files(tmp_path, monkeypatch, confirmation):
    def unexpected(*args, **kwargs):
        raise AssertionError("filesystem must not be accessed")

    monkeypatch.setattr(type(tmp_path), "lstat", unexpected)
    importer = LocalTextKnowledgeImporter(tmp_path / "absent")
    with pytest.raises(KnowledgeFileImportError, match="read-not-authorized"):
        await importer.load((".",), confirm_read=confirmation)


@pytest.mark.asyncio
@pytest.mark.parametrize("paths", [
    ["a.txt"], ("../a.txt",), ("/a.txt",), ("C:/a.txt",), ("a\\b.txt",),
    ("a.txt:secret",), ("a//b.txt",), ("a/./b.txt",), ("a.txt ",),
    ("*.txt",), ("a\x00.txt",), ("a.txt", "a.txt"), (123,),
])
async def test_invalid_selection_rejected_before_io(tmp_path, paths):
    with pytest.raises(KnowledgeFileImportError, match="selection-invalid"):
        await LocalTextKnowledgeImporter(tmp_path / "absent").load(paths, confirm_read=True)


@pytest.mark.asyncio
async def test_empty_selection_is_no_io_and_empty_import(tmp_path):
    result = await LocalTextKnowledgeImporter(tmp_path / "absent").load((), confirm_read=True)
    assert result.documents == result.records == ()


@pytest.mark.asyncio
async def test_utf8_raw_fingerprints_source_records_and_snapshot_wiring(tmp_path):
    data = b"\xef\xbb\xbf" + "退款🙂\r\n七天".encode()
    (tmp_path / "manual.txt").write_bytes(data)
    (tmp_path / "blank.md").write_bytes(b" \r\n")
    importer = LocalTextKnowledgeImporter(tmp_path)
    first = await importer.load((".",), confirm_read=True)
    assert first == await importer.load(("manual.txt", "blank.md"), confirm_read=True)
    assert [item.relative_path for item in first.records] == ["blank.md", "manual.txt"]
    assert first.records[0].document_id is None
    document = first.documents[0]
    assert document.text == "退款🙂\r\n七天"
    assert document.source == "local:manual.txt" and document.title == "manual.txt"
    assert first.records[1].raw_digest == hashlib.sha256(data).hexdigest()
    assert first.records[1].raw_bytes == len(data)
    assert first.records[1].text_digest == hashlib.sha256(document.text.encode()).hexdigest()
    encoded = first.to_manifest_json()
    assert "退款" not in encoded and str(tmp_path) not in encoded
    assert "manual.txt" not in repr(first)
    assert first.digest == hashlib.sha256(encoded.encode()).hexdigest()
    assert json.loads(encoded)["format"] == "wagent-knowledge-text-import-v1"
    snapshot = prepare_knowledge_snapshot("support", "v1", first.documents, splitter=Utf8KnowledgeTextSplitter(8))
    assert "".join(item.text for item in snapshot.documents) == document.text
    assert all(item.source == document.source for item in snapshot.documents)


@pytest.mark.asyncio
async def test_selection_is_sorted_recursive_opt_in_and_overlaps_deduplicate(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "z.MD").write_text("z", encoding="utf-8")
    (tmp_path / "skip.py").write_text("raise RuntimeError()", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    shallow = await LocalTextKnowledgeImporter(tmp_path).load((".",), confirm_read=True)
    assert [item.relative_path for item in shallow.records] == ["a.txt", "z.MD"]
    deep = await LocalTextKnowledgeImporter(tmp_path, recursive=True).load((".", "sub/b.txt", "sub"), confirm_read=True)
    assert [item.relative_path for item in deep.records] == ["a.txt", "sub/b.txt", "z.MD"]
    with pytest.raises(KnowledgeFileImportError):
        await LocalTextKnowledgeImporter(tmp_path).load(("skip.py",), confirm_read=True)


@pytest.mark.asyncio
async def test_hidden_entries_require_separate_configuration(tmp_path):
    (tmp_path / ".secret.txt").write_text("secret", encoding="utf-8")
    default = LocalTextKnowledgeImporter(tmp_path)
    assert not (await default.load((".",), confirm_read=True)).records
    with pytest.raises(KnowledgeFileImportError):
        await default.load((".secret.txt",), confirm_read=True)
    result = await replace(default, include_hidden=True).load((".",), confirm_read=True)
    assert len(result.documents) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"\xff", b"text\x00binary"])
async def test_invalid_text_fails_without_partial_results_or_body_disclosure(tmp_path, data):
    (tmp_path / "a.txt").write_bytes(b"valid")
    (tmp_path / "PRIVATE.txt").write_bytes(data)
    with pytest.raises(KnowledgeFileImportError) as error:
        await LocalTextKnowledgeImporter(tmp_path).load((".",), confirm_read=True)
    assert str(error.value) == "knowledge-file-import-failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"max_files": 1}, {"max_entries": 1}, {"max_file_bytes": 3}, {"max_total_bytes": 7}])
async def test_raw_limits_reject_before_parser_calls(tmp_path, options):
    (tmp_path / "a.txt").write_bytes(b"abcd")
    (tmp_path / "b.txt").write_bytes(b"efgh")

    class Parser:
        parser_key = "never"
        calls = 0

        def parse(self, data, *, relative_path):
            self.calls += 1
            return "text"

    parser = Parser()
    with pytest.raises(KnowledgeFileImportError):
        await LocalTextKnowledgeImporter(tmp_path, parser=parser, **options).load((".",), confirm_read=True)
    assert parser.calls == 0


@pytest.mark.asyncio
async def test_recursive_directory_depth_is_bounded(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "c.txt").write_text("body", encoding="utf-8")
    with pytest.raises(KnowledgeFileImportError):
        await LocalTextKnowledgeImporter(tmp_path, recursive=True, max_depth=1).load((".",), confirm_read=True)


@pytest.mark.asyncio
async def test_custom_parser_identity_and_expansion_limits(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"a")

    class Parser:
        parser_key = "host-parser-v1"
        output = "parsed"

        def parse(self, data, *, relative_path):
            assert data == b"a" and relative_path == "a.txt"
            return self.output

    parser = Parser()
    importer = LocalTextKnowledgeImporter(tmp_path, parser=parser, max_file_bytes=8)
    first = await importer.load(("a.txt",), confirm_read=True)
    parser.parser_key = "host-parser-v2"
    second = await importer.load(("a.txt",), confirm_read=True)
    assert first.documents[0].document_id != second.documents[0].document_id
    parser.output = "x" * 9
    with pytest.raises(KnowledgeFileImportError):
        await importer.load(("a.txt",), confirm_read=True)
    parser.output = 123
    with pytest.raises(KnowledgeFileImportError):
        await importer.load(("a.txt",), confirm_read=True)


@pytest.mark.asyncio
async def test_source_change_after_selection_is_rejected(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"a")
    second = tmp_path / "b.txt"
    second.write_bytes(b"b")

    class Parser:
        parser_key = "mutation-demo"

        def parse(self, data, *, relative_path):
            if relative_path == "a.txt":
                second.write_bytes(b"changed-size")
            return data.decode()

    with pytest.raises(KnowledgeFileImportError):
        await LocalTextKnowledgeImporter(tmp_path, parser=Parser()).load((".",), confirm_read=True)


@pytest.mark.asyncio
async def test_symlink_selection_rejected_when_platform_allows_creation(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("body", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(KnowledgeFileImportError):
        await LocalTextKnowledgeImporter(tmp_path).load(("link.txt",), confirm_read=True)


def test_windows_reparse_points_rejected_even_if_reported_as_directories():
    with pytest.raises(ValueError):
        _reject_link(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400))


@pytest.mark.asyncio
async def test_fifo_is_rejected_without_opening(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation unavailable")
    os.mkfifo(tmp_path / "pipe.txt")
    with pytest.raises(KnowledgeFileImportError):
        await LocalTextKnowledgeImporter(tmp_path).load(("pipe.txt",), confirm_read=True)


@pytest.mark.asyncio
async def test_cancel_drains_started_parser_without_returning_partial_import(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"body")
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    class Parser:
        parser_key = "blocking-demo"

        def parse(self, data, *, relative_path):
            started.set()
            try:
                if not release.wait(5):
                    raise RuntimeError("parser timed out")
                return "body"
            finally:
                finished.set()

    task = asyncio.create_task(LocalTextKnowledgeImporter(tmp_path, parser=Parser()).load(("a.txt",), confirm_read=True))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


@pytest.mark.asyncio
async def test_result_rejects_inconsistent_records(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"body")
    result = await LocalTextKnowledgeImporter(tmp_path).load(("a.txt",), confirm_read=True)
    with pytest.raises(ValueError):
        KnowledgeTextImport(result.parser_key, result.documents, (replace(result.records[0], text_digest="0" * 64),))
    with pytest.raises(ValueError):
        replace(result, records=())


@pytest.mark.asyncio
async def test_same_tree_under_another_root_preserves_identity(tmp_path):
    first_root, second_root = tmp_path / "one", tmp_path / "two"
    first_root.mkdir()
    second_root.mkdir()
    for root in (first_root, second_root):
        (root / "a.txt").write_bytes(b"same content")
    first = await LocalTextKnowledgeImporter(first_root).load(("a.txt",), confirm_read=True)
    second = await LocalTextKnowledgeImporter(second_root).load(("a.txt",), confirm_read=True)
    assert first == second and first.digest == second.digest
    (second_root / "a.txt").write_bytes(b"changed content")
    changed = await LocalTextKnowledgeImporter(second_root).load(("a.txt",), confirm_read=True)
    assert changed.documents[0].document_id != first.documents[0].document_id


@pytest.mark.asyncio
async def test_custom_parser_error_is_sanitized(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"body")

    class Parser:
        parser_key = "failing-parser"

        def parse(self, data, *, relative_path):
            raise RuntimeError("PRIVATE_BODY_AND_PATH")

    with pytest.raises(KnowledgeFileImportError) as error:
        await LocalTextKnowledgeImporter(tmp_path, parser=Parser()).load(("a.txt",), confirm_read=True)
    assert str(error.value) == "knowledge-file-import-failed"
