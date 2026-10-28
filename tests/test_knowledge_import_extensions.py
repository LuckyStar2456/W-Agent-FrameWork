"""Import acceptance: extraction, incremental reuse, provenance and commit locks."""

import hashlib
import json
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from typer.testing import CliRunner

from w_agent.knowledge_files import KnowledgeFileImportError, LocalTextKnowledgeImporter
from w_agent.knowledge_management import LocalKnowledgeRequest, manage_local_knowledge
from w_agent.knowledge_parsers import KnowledgeParserDependencyError, OptionalDocumentKnowledgeParser
from w_agent.knowledge_provenance import TracedKnowledgeImport, compare_knowledge_imports, prepare_traced_knowledge_import
from w_agent.knowledge_sqlite import KnowledgeStoreError


@pytest.mark.asyncio
async def test_incremental_reads_hashes_and_reuses_only_unchanged_parser_output(tmp_path):
    class Parser:
        parser_key = "v1"
        calls = []

        def parse(self, data, *, relative_path):
            self.calls.append(relative_path)
            return data.decode()

    parser = Parser()
    importer = LocalTextKnowledgeImporter(tmp_path, parser=parser)
    for name in ("same", "changed", "removed"):
        (tmp_path / (name + ".txt")).write_text(name, encoding="utf-8")
    first = await importer.load((".",), confirm_read=True)
    parser.calls.clear()
    (tmp_path / "changed.txt").write_text("new body", encoding="utf-8")
    (tmp_path / "added.txt").write_text("new", encoding="utf-8")
    # A narrower selection, without deleting actual files.
    second = await importer.load(("same.txt", "changed.txt", "added.txt"), previous=first, confirm_read=True)
    assert parser.calls == ["added.txt", "changed.txt"]
    delta = compare_knowledge_imports(first, second)
    assert (delta.added, delta.changed, delta.removed, delta.unchanged) == (("added.txt",), ("changed.txt",), ("removed.txt",), ("same.txt",))
    parser.calls.clear()
    parser.parser_key = "v2"
    third = await importer.load(("same.txt",), previous=second, confirm_read=True)
    assert parser.calls == ["same.txt"]
    assert compare_knowledge_imports(second, third).changed == ("same.txt",)


@pytest.mark.asyncio
async def test_trace_offsets_roundtrip_originals_and_tamper_rejection(tmp_path):
    original = "🙂    退款\r\n重复重复"
    (tmp_path / "body.md").write_bytes(b"\xef\xbb\xbf" + original.encode())
    imported = await LocalTextKnowledgeImporter(tmp_path).load(("body.md",), confirm_read=True)
    traced = prepare_traced_knowledge_import("n", "v", imported, chunk_bytes=4)
    assert "body.md" not in repr(traced) and original not in repr(traced)
    for chunk, origin in zip(traced.snapshot.documents, traced.origins):
        assert original[origin.char_start:origin.char_end] == chunk.text
        assert original.encode()[origin.byte_start:origin.byte_end].decode() == chunk.text
    assert TracedKnowledgeImport.from_json(traced.to_json(), expected_digest=traced.digest) == traced
    assert json.loads(traced.to_json())["sources"][0]["text"] == original
    broken = json.loads(traced.to_json())
    broken["origins"][0]["byte_end"] += 1
    encoded = json.dumps(broken, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    with pytest.raises(ValueError, match="invalid traced"):
        TracedKnowledgeImport.from_json(encoded, expected_digest=hashlib.sha256(encoded.encode()).hexdigest())
    with pytest.raises(ValueError):
        TracedKnowledgeImport.from_json(traced.to_json(), expected_digest="0" * 64)


def test_optional_parser_is_lazy_and_reports_missing_dependency(monkeypatch):
    import w_agent.knowledge_parsers as module

    def absent(name):
        raise ImportError("PRIVATE")

    monkeypatch.setattr(module.importlib, "import_module", absent)
    parser = OptionalDocumentKnowledgeParser()
    assert parser.parse(b"text", relative_path="x.md") == "text"
    with pytest.raises(KnowledgeParserDependencyError, match="^knowledge-parser-dependency-unavailable:pypdf$"):
        parser.parse(b"pdf", relative_path="x.pdf")


def test_pdf_extraction_boundaries_with_injected_reader(monkeypatch):
    import w_agent.knowledge_parsers as module

    reader = SimpleNamespace(is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda: "first"), SimpleNamespace(extract_text=lambda: "second")])
    monkeypatch.setattr(module.importlib, "import_module", lambda name: SimpleNamespace(PdfReader=lambda stream: reader))
    assert OptionalDocumentKnowledgeParser().parse(b"pdf", relative_path="x.pdf") == "first\nsecond"
    with pytest.raises(ValueError, match="text limit"):
        OptionalDocumentKnowledgeParser(max_text_bytes=4).parse(b"pdf", relative_path="x.pdf")
    reader.is_encrypted = True
    with pytest.raises(ValueError, match="encrypted"):
        OptionalDocumentKnowledgeParser().parse(b"pdf", relative_path="x.pdf")


def test_office_archive_expansion_rejected_before_dependency_load(monkeypatch):
    import w_agent.knowledge_parsers as module

    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("oversized.xml", "x" * 20)
    monkeypatch.setattr(module.importlib, "import_module", lambda name: pytest.fail("parser must not load"))
    with pytest.raises(ValueError, match="archive limit"):
        OptionalDocumentKnowledgeParser(max_zip_bytes=10).parse(stream.getvalue(), relative_path="x.docx")


@pytest.mark.asyncio
async def test_real_docx_import_preview_commit_and_keyword_search(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("refund first")
    document.add_table(rows=1, cols=2).rows[0].cells[0].text = "table policy"
    document.add_paragraph("refund last")
    document.save(tmp_path / "policy.docx")
    request = LocalKnowledgeRequest("import", tmp_path / "db.sqlite", namespace="n", version="v", root=tmp_path,
                                    paths=("policy.docx",), confirm_read=True, document_formats=True)
    preview = await manage_local_knowledge(request)
    saved = await manage_local_knowledge(replace(request, confirm_write=True, confirm_create=True,
                                                expected_preview_digest=preview["preview_digest"]))
    assert saved["preview_locked"] and saved["digest"] == preview["digest"]
    result = await manage_local_knowledge(LocalKnowledgeRequest("search", request.database, namespace="n", version="v",
                                                               query="refund", confirm_read=True, include_text=True))
    assert result["matches"][0]["text"] == "refund first\ntable policy\t\nrefund last"


@pytest.mark.parametrize("extension,module", [("pdf", "pypdf"), ("xlsx", "openpyxl"), ("pptx", "pptx")])
def test_real_optional_document_parsers_when_available(extension, module):
    dependency = pytest.importorskip(module)
    stream = BytesIO()
    if extension == "pdf":
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = dependency.PdfWriter()
        page = writer.add_blank_page(width=200, height=100)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
        })
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 10 50 Td (refund seven days) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.write(stream)
        expected = "refund seven days"
    elif extension == "xlsx":
        workbook = dependency.Workbook()
        workbook.active.append(["policy", 7])
        workbook.save(stream)
        workbook.close()
        expected = "[Sheet]\npolicy\t7"
    else:
        presentation = dependency.Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = "policy"
        presentation.save(stream)
        expected = "policy\n"
    assert OptionalDocumentKnowledgeParser().parse(stream.getvalue(), relative_path="sample." + extension) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["body", "chunk", "destination", "version", "raw_bom"])
async def test_preview_lock_rejects_drift_before_database_creation(tmp_path, change):
    path = tmp_path / "body.txt"
    path.write_bytes(b"same")
    request = LocalKnowledgeRequest("import", tmp_path / "db.sqlite", namespace="n", version="v", root=tmp_path,
                                    paths=("body.txt",), confirm_read=True)
    preview = await manage_local_knowledge(request)
    if change in ("body", "raw_bom"):
        path.write_bytes(b"different" if change == "body" else b"\xef\xbb\xbfsame")
    elif change == "chunk":
        request = replace(request, chunk_bytes=4)
    elif change == "destination":
        request = replace(request, database=tmp_path / "other.sqlite")
    else:
        request = replace(request, version="v2")
    with pytest.raises(KnowledgeStoreError, match="knowledge-preview-conflict") as error:
        await manage_local_knowledge(replace(request, confirm_write=True, confirm_create=True,
                                            expected_preview_digest=preview["preview_digest"]))
    assert not error.value.may_have_written and not request.database.exists()


def test_cli_preview_locked_commit(tmp_path):
    from w_agent.cli import app

    (tmp_path / "a.md").write_text("content", encoding="utf-8")
    arguments = ["knowledge-import", "--database", str(tmp_path / "db.sqlite"), "--root", str(tmp_path),
                 "--path", "a.md", "--namespace", "n", "--version", "v", "--confirm-read"]
    preview = CliRunner().invoke(app, arguments)
    assert preview.exit_code == 0, preview.output
    digest = json.loads(preview.output)["preview_digest"]
    saved = CliRunner().invoke(app, arguments + ["--confirm-write", "--confirm-create", "--expected-preview-digest", digest])
    assert saved.exit_code == 0, saved.output
    assert json.loads(saved.output)["preview_locked"] is True
