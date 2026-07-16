from __future__ import annotations

import subprocess
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import splicr.document_import as document_import_module
from splicr.document_import import (
    DocumentFormat,
    DocumentImportError,
    DocumentImportErrorCode,
    import_document,
)


def _archive(parts: dict[str, str | bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return output.getvalue()


def _docx() -> bytes:
    document_xml = """\
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Chapter One</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r>
      <w:r><w:t xml:space="preserve"> and </w:t></w:r>
      <w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr>
      <w:r><w:t>First item</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""
    numbering_xml = """\
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="3">
    <w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="7"><w:abstractNumId w:val="3"/></w:num>
</w:numbering>
"""
    return _archive(
        {
            "[Content_Types].xml": "<Types/>",
            "word/document.xml": document_xml,
            "word/numbering.xml": numbering_xml,
        }
    )


def _odt() -> bytes:
    content_xml = """\
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0">
  <office:automatic-styles>
    <style:style style:name="Strong" style:family="text">
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Emphasis" style:family="text">
      <style:text-properties fo:font-style="italic"/>
    </style:style>
    <text:list-style style:name="Numbered">
      <text:list-level-style-number text:level="1"/>
    </text:list-style>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:outline-level="2">A Section</text:h>
      <text:p><text:span text:style-name="Strong">Bold</text:span> and <text:span text:style-name="Emphasis">italic</text:span></text:p>
      <text:list text:style-name="Numbered">
        <text:list-item><text:p>First item</text:p></text:list-item>
        <text:list-item><text:p>Second item</text:p></text:list-item>
      </text:list>
    </office:text>
  </office:body>
</office:document-content>
"""
    return _archive(
        {"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content_xml}
    )


def test_markdown_is_preserved_and_title_is_inferred() -> None:
    source = "# Story\r\n\r\nA *quiet* beginning."

    imported = import_document("story.markdown", source.encode(), max_upload_bytes=1_000)

    assert imported.source_format is DocumentFormat.MARKDOWN
    assert imported.markdown == "# Story\n\nA *quiet* beginning."
    assert imported.text == imported.markdown
    assert imported.title == "Story"


def test_markdown_leading_indentation_is_not_discarded() -> None:
    imported = import_document(
        "code.md",
        b"    preserved code block\n",
        max_upload_bytes=1_000,
    )

    assert imported.markdown == "    preserved code block"


def test_json_is_rendered_as_readable_markdown() -> None:
    source = b'{"title":"A Tale","chapters":["Opening","Ending"]}'

    imported = import_document("story.json", source, max_upload_bytes=1_000)

    assert "# title\n\nA Tale" in imported.markdown
    assert "# chapters" in imported.markdown
    assert "- Opening\n- Ending" in imported.markdown


def test_docx_preserves_headings_emphasis_and_numbered_lists() -> None:
    imported = import_document(
        "structured.docx",
        _docx(),
        max_upload_bytes=20_000,
        max_expanded_bytes=20_000,
    )

    assert imported.source_format is DocumentFormat.DOCX
    assert "# Chapter One" in imported.markdown
    assert "**Bold** and *italic*" in imported.markdown
    assert "1. First item" in imported.markdown


def test_odt_preserves_headings_emphasis_and_numbered_lists() -> None:
    imported = import_document(
        "structured.odt",
        _odt(),
        max_upload_bytes=20_000,
        max_expanded_bytes=20_000,
    )

    assert imported.source_format is DocumentFormat.ODT
    assert "## A Section" in imported.markdown
    assert "**Bold** and *italic*" in imported.markdown
    assert "1. First item\n1. Second item" in imported.markdown


def test_upload_and_expanded_archive_limits_have_distinct_error_codes() -> None:
    with pytest.raises(DocumentImportError) as upload_error:
        import_document("story.txt", b"too large", max_upload_bytes=3)
    assert upload_error.value.code is DocumentImportErrorCode.FILE_TOO_LARGE

    with pytest.raises(DocumentImportError) as expanded_error:
        import_document(
            "structured.docx",
            _docx(),
            max_upload_bytes=20_000,
            max_expanded_bytes=20,
        )
    assert expanded_error.value.code is DocumentImportErrorCode.EXPANDED_FILE_TOO_LARGE


@pytest.mark.parametrize(
    ("filename", "content", "expected_code"),
    [
        ("story.pdf", b"content", DocumentImportErrorCode.UNSUPPORTED_FORMAT),
        ("story.txt", b"\xff", DocumentImportErrorCode.INVALID_ENCODING),
        ("story.json", b"{bad", DocumentImportErrorCode.MALFORMED_DOCUMENT),
        ("story.docx", b"not a zip", DocumentImportErrorCode.MALFORMED_DOCUMENT),
        ("story.md", b" \n\t ", DocumentImportErrorCode.EMPTY_DOCUMENT),
    ],
)
def test_invalid_documents_have_stable_error_codes(
    filename: str,
    content: bytes,
    expected_code: DocumentImportErrorCode,
) -> None:
    with pytest.raises(DocumentImportError) as error:
        import_document(filename, content, max_upload_bytes=1_000)

    assert error.value.code is expected_code
    assert error.value.filename == filename


def test_legacy_doc_reports_when_configured_converter_is_missing() -> None:
    missing_soffice = Path.cwd() / ".missing-soffice-for-document-import-test.exe"

    with pytest.raises(DocumentImportError) as error:
        import_document(
            "legacy.doc",
            b"legacy content",
            max_upload_bytes=1_000,
            soffice_path=missing_soffice,
        )

    assert error.value.code is DocumentImportErrorCode.CONVERTER_UNAVAILABLE
    assert "LibreOffice" in str(error.value)


def test_legacy_doc_conversion_output_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converted_docx = _docx()
    monkeypatch.setattr(document_import_module.tempfile, "tempdir", str(Path.cwd()))

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output_directory = Path(command[command.index("--outdir") + 1])
        (output_directory / "source.docx").write_bytes(converted_docx)
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(document_import_module.subprocess, "run", fake_run)

    imported = import_document(
        "legacy.doc",
        b"legacy content",
        max_upload_bytes=20_000,
        max_expanded_bytes=20_000,
        soffice_path=sys.executable,
    )

    assert imported.source_format is DocumentFormat.LEGACY_DOC
    assert "# Chapter One" in imported.markdown
