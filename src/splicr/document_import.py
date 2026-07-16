from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class DocumentFormat(StrEnum):
    TEXT = "txt"
    MARKDOWN = "markdown"
    JSON = "json"
    DOCX = "docx"
    ODT = "odt"
    LEGACY_DOC = "doc"


class DocumentImportErrorCode(StrEnum):
    UNSUPPORTED_FORMAT = "unsupported_format"
    FILE_TOO_LARGE = "file_too_large"
    EXPANDED_FILE_TOO_LARGE = "expanded_file_too_large"
    INVALID_ENCODING = "invalid_encoding"
    MALFORMED_DOCUMENT = "malformed_document"
    EMPTY_DOCUMENT = "empty_document"
    CONVERTER_UNAVAILABLE = "converter_unavailable"
    CONVERSION_FAILED = "conversion_failed"


class DocumentImportError(ValueError):
    """A stable, user-displayable document import failure."""

    def __init__(
        self,
        code: DocumentImportErrorCode,
        message: str,
        *,
        filename: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.filename = filename


@dataclass(frozen=True, slots=True)
class ImportedDocument:
    filename: str
    source_format: DocumentFormat
    markdown: str
    source_bytes: int
    title: str | None

    @property
    def text(self) -> str:
        """Provider-neutral alias for callers that do not care about the normalization format."""

        return self.markdown


SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {".txt", ".md", ".markdown", ".json", ".docx", ".odt", ".doc"}
)

_FORMAT_BY_EXTENSION = {
    ".txt": DocumentFormat.TEXT,
    ".md": DocumentFormat.MARKDOWN,
    ".markdown": DocumentFormat.MARKDOWN,
    ".json": DocumentFormat.JSON,
    ".docx": DocumentFormat.DOCX,
    ".odt": DocumentFormat.ODT,
    ".doc": DocumentFormat.LEGACY_DOC,
}

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_W_NS}}}"

_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_STYLE_NS = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
_FO_NS = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_OFFICE = f"{{{_OFFICE_NS}}}"
_TEXT = f"{{{_TEXT_NS}}}"
_STYLE = f"{{{_STYLE_NS}}}"
_FO = f"{{{_FO_NS}}}"
_TABLE = f"{{{_TABLE_NS}}}"


def import_document(
    filename: str,
    content: bytes,
    *,
    max_upload_bytes: int,
    max_expanded_bytes: int | None = None,
    soffice_path: str | os.PathLike[str] | None = None,
    conversion_timeout_seconds: float = 60.0,
) -> ImportedDocument:
    """Normalize a supported document into Markdown-like text.

    ``max_upload_bytes`` is intentionally required so every transport integration makes an
    explicit upload-size decision. ``max_expanded_bytes`` bounds decompressed Office documents
    and LibreOffice conversion output; by default it is ten times the upload limit.
    """

    if max_upload_bytes <= 0:
        raise ValueError("max_upload_bytes must be positive")
    if max_expanded_bytes is None:
        max_expanded_bytes = max_upload_bytes * 10
    if max_expanded_bytes <= 0:
        raise ValueError("max_expanded_bytes must be positive")
    if conversion_timeout_seconds <= 0:
        raise ValueError("conversion_timeout_seconds must be positive")

    safe_filename = Path(filename.replace("\\", "/")).name
    extension = Path(safe_filename).suffix.lower()
    source_format = _FORMAT_BY_EXTENSION.get(extension)
    if source_format is None:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise DocumentImportError(
            DocumentImportErrorCode.UNSUPPORTED_FORMAT,
            f"Unsupported document type {extension or '(none)'}. Supported types: {supported}.",
            filename=safe_filename,
        )

    payload = bytes(content)
    if len(payload) > max_upload_bytes:
        raise DocumentImportError(
            DocumentImportErrorCode.FILE_TOO_LARGE,
            f"Document is {len(payload)} bytes; the upload limit is {max_upload_bytes} bytes.",
            filename=safe_filename,
        )

    if source_format is DocumentFormat.TEXT:
        markdown = _decode_utf8(payload, safe_filename)
    elif source_format is DocumentFormat.MARKDOWN:
        markdown = _decode_utf8(payload, safe_filename)
    elif source_format is DocumentFormat.JSON:
        markdown = _extract_json(payload, safe_filename)
    elif source_format is DocumentFormat.DOCX:
        markdown = _extract_docx(payload, safe_filename, max_expanded_bytes)
    elif source_format is DocumentFormat.ODT:
        markdown = _extract_odt(payload, safe_filename, max_expanded_bytes)
    else:
        converted = _convert_legacy_doc(
            payload,
            safe_filename,
            max_expanded_bytes=max_expanded_bytes,
            soffice_path=soffice_path,
            timeout_seconds=conversion_timeout_seconds,
        )
        markdown = _extract_docx(converted, safe_filename, max_expanded_bytes)

    markdown = _normalize_markdown(markdown)
    if not markdown.strip():
        raise DocumentImportError(
            DocumentImportErrorCode.EMPTY_DOCUMENT,
            "The document contains no readable text.",
            filename=safe_filename,
        )

    return ImportedDocument(
        filename=safe_filename,
        source_format=source_format,
        markdown=markdown,
        source_bytes=len(payload),
        title=_infer_title(markdown),
    )


def _decode_utf8(content: bytes, filename: str) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentImportError(
            DocumentImportErrorCode.INVALID_ENCODING,
            "Text and Markdown documents must use UTF-8 encoding.",
            filename=filename,
        ) from error
    if "\x00" in text:
        raise DocumentImportError(
            DocumentImportErrorCode.INVALID_ENCODING,
            "The document contains null bytes and does not appear to be UTF-8 text.",
            filename=filename,
        )
    return text


def _extract_json(content: bytes, filename: str) -> str:
    text = _decode_utf8(content, filename)
    try:
        value = json.loads(text, parse_constant=lambda value: _reject_json_constant(value))
        return _json_to_markdown(value)
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise DocumentImportError(
            DocumentImportErrorCode.MALFORMED_DOCUMENT,
            "The JSON document is invalid or nested too deeply.",
            filename=filename,
        ) from error


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-standard JSON constant: {value}")


def _json_to_markdown(value: Any, level: int = 1) -> str:
    if isinstance(value, dict):
        if not value:
            return "Empty object"
        blocks: list[str] = []
        for key, child in value.items():
            heading_level = min(level, 6)
            blocks.append(f"{'#' * heading_level} {_escape_markdown_inline(str(key))}")
            blocks.append(_json_to_markdown(child, level + 1))
        return "\n\n".join(blocks)

    if isinstance(value, list):
        if not value:
            return "Empty list"
        if all(_is_json_scalar(item) for item in value):
            return "\n".join(f"- {_json_scalar(item)}" for item in value)
        blocks = []
        for index, child in enumerate(value, start=1):
            if _is_json_scalar(child):
                blocks.append(f"- {_json_scalar(child)}")
            else:
                heading_level = min(level, 6)
                blocks.append(f"{'#' * heading_level} Item {index}")
                blocks.append(_json_to_markdown(child, level + 1))
        return "\n\n".join(blocks)

    return _json_scalar(value)


def _is_json_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _json_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _read_archive_parts(
    content: bytes,
    *,
    filename: str,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    max_expanded_bytes: int,
) -> dict[str, bytes]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if any(info.flag_bits & 0x1 for info in infos):
                raise DocumentImportError(
                    DocumentImportErrorCode.MALFORMED_DOCUMENT,
                    "Encrypted Office documents are not supported.",
                    filename=filename,
                )
            expanded_size = sum(info.file_size for info in infos)
            if expanded_size > max_expanded_bytes:
                raise DocumentImportError(
                    DocumentImportErrorCode.EXPANDED_FILE_TOO_LARGE,
                    (
                        f"Document expands to {expanded_size} bytes; the expanded-file limit is "
                        f"{max_expanded_bytes} bytes."
                    ),
                    filename=filename,
                )

            names = set(archive.namelist())
            missing = [name for name in required if name not in names]
            if missing:
                raise DocumentImportError(
                    DocumentImportErrorCode.MALFORMED_DOCUMENT,
                    f"The Office document is missing {', '.join(missing)}.",
                    filename=filename,
                )
            return {name: archive.read(name) for name in (*required, *optional) if name in names}
    except DocumentImportError:
        raise
    except (BadZipFile, OSError, RuntimeError) as error:
        raise DocumentImportError(
            DocumentImportErrorCode.MALFORMED_DOCUMENT,
            "The Office document is not a readable ZIP-based document.",
            filename=filename,
        ) from error


def _parse_xml(content: bytes, filename: str) -> ElementTree.Element:
    upper_content = content.upper()
    if b"<!DOCTYPE" in upper_content or b"<!ENTITY" in upper_content:
        raise DocumentImportError(
            DocumentImportErrorCode.MALFORMED_DOCUMENT,
            "Office documents containing XML document type declarations are not supported.",
            filename=filename,
        )
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise DocumentImportError(
            DocumentImportErrorCode.MALFORMED_DOCUMENT,
            "The Office document contains malformed XML.",
            filename=filename,
        ) from error


def _extract_docx(content: bytes, filename: str, max_expanded_bytes: int) -> str:
    parts = _read_archive_parts(
        content,
        filename=filename,
        required=("word/document.xml",),
        optional=("word/numbering.xml",),
        max_expanded_bytes=max_expanded_bytes,
    )
    document = _parse_xml(parts["word/document.xml"], filename)
    numbering = _docx_numbering(parts.get("word/numbering.xml"), filename)
    body = document.find(f"{_W}body")
    if body is None:
        raise DocumentImportError(
            DocumentImportErrorCode.MALFORMED_DOCUMENT,
            "The Word document has no document body.",
            filename=filename,
        )

    blocks: list[str] = []
    for child in body:
        if child.tag == f"{_W}p":
            block = _docx_paragraph(child, numbering)
        elif child.tag == f"{_W}tbl":
            block = _docx_table(child)
        else:
            continue
        if block:
            blocks.append(block)
    return _join_blocks(blocks)


def _docx_numbering(content: bytes | None, filename: str) -> dict[tuple[str, int], str]:
    if content is None:
        return {}
    root = _parse_xml(content, filename)
    abstract_formats: dict[tuple[str, int], str] = {}
    for abstract in root.findall(f"{_W}abstractNum"):
        abstract_id = abstract.get(f"{_W}abstractNumId", "")
        for level in abstract.findall(f"{_W}lvl"):
            level_index = int(level.get(f"{_W}ilvl", "0"))
            number_format = level.find(f"{_W}numFmt")
            if number_format is not None:
                abstract_formats[(abstract_id, level_index)] = number_format.get(
                    f"{_W}val", "bullet"
                )

    formats: dict[tuple[str, int], str] = {}
    for number in root.findall(f"{_W}num"):
        number_id = number.get(f"{_W}numId", "")
        abstract_ref = number.find(f"{_W}abstractNumId")
        if abstract_ref is None:
            continue
        abstract_id = abstract_ref.get(f"{_W}val", "")
        for (candidate_id, level), number_format in abstract_formats.items():
            if candidate_id == abstract_id:
                formats[(number_id, level)] = number_format
    return formats


def _docx_paragraph(paragraph: ElementTree.Element, numbering: dict[tuple[str, int], str]) -> str:
    rendered = "".join(_docx_run(run) for run in paragraph.iter(f"{_W}r"))
    rendered = rendered.strip()
    if not rendered:
        return ""

    properties = paragraph.find(f"{_W}pPr")
    style_name = ""
    if properties is not None:
        style = properties.find(f"{_W}pStyle")
        if style is not None:
            style_name = style.get(f"{_W}val", "")

    heading_level = _heading_level(style_name)
    if heading_level is not None:
        return f"{'#' * heading_level} {rendered}"

    list_details = _docx_list_details(properties, style_name, numbering)
    if list_details is not None:
        level, ordered = list_details
        marker = "1." if ordered else "-"
        return f"{'  ' * level}{marker} {rendered}"

    if "quote" in style_name.lower():
        return "> " + rendered.replace("\n", "\n> ")
    return rendered


def _docx_list_details(
    properties: ElementTree.Element | None,
    style_name: str,
    numbering: dict[tuple[str, int], str],
) -> tuple[int, bool] | None:
    if properties is not None:
        number_properties = properties.find(f"{_W}numPr")
        if number_properties is not None:
            level_element = number_properties.find(f"{_W}ilvl")
            number_element = number_properties.find(f"{_W}numId")
            level = int(level_element.get(f"{_W}val", "0")) if level_element is not None else 0
            number_id = number_element.get(f"{_W}val", "") if number_element is not None else ""
            number_format = numbering.get((number_id, level), "bullet")
            return level, number_format not in {"bullet", "none"}

    normalized_style = style_name.lower().replace(" ", "")
    if normalized_style.startswith("listbullet"):
        return 0, False
    if normalized_style.startswith("listnumber"):
        return 0, True
    return None


def _docx_run(run: ElementTree.Element) -> str:
    parts: list[str] = []
    for child in run:
        if child.tag == f"{_W}t":
            parts.append(_escape_markdown_inline(child.text or ""))
        elif child.tag == f"{_W}tab":
            parts.append("\t")
        elif child.tag in {f"{_W}br", f"{_W}cr"}:
            parts.append("\n")
        elif child.tag == f"{_W}noBreakHyphen":
            parts.append("-")

    text = "".join(parts)
    properties = run.find(f"{_W}rPr")
    if not text or properties is None:
        return text
    return _apply_emphasis(
        text,
        bold=_word_property_enabled(properties.find(f"{_W}b")),
        italic=_word_property_enabled(properties.find(f"{_W}i")),
        strike=_word_property_enabled(properties.find(f"{_W}strike")),
    )


def _word_property_enabled(element: ElementTree.Element | None) -> bool:
    if element is None:
        return False
    return element.get(f"{_W}val", "true").lower() not in {"false", "0", "off", "none"}


def _docx_table(table: ElementTree.Element) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{_W}tr"):
        cells: list[str] = []
        for cell in row.findall(f"{_W}tc"):
            paragraphs = [_docx_paragraph(paragraph, {}) for paragraph in cell.findall(f"{_W}p")]
            cell_text = "<br>".join(part for part in paragraphs if part)
            cells.append(cell_text.replace("|", "\\|"))
        if cells:
            rows.append(cells)
    return _markdown_table(rows)


def _extract_odt(content: bytes, filename: str, max_expanded_bytes: int) -> str:
    parts = _read_archive_parts(
        content,
        filename=filename,
        required=("content.xml",),
        optional=("styles.xml",),
        max_expanded_bytes=max_expanded_bytes,
    )
    content_root = _parse_xml(parts["content.xml"], filename)
    style_roots = [content_root]
    if "styles.xml" in parts:
        style_roots.append(_parse_xml(parts["styles.xml"], filename))
    styles = _odt_text_styles(style_roots)
    lists = _odt_list_styles(style_roots)

    office_text = content_root.find(f".//{_OFFICE}text")
    if office_text is None:
        raise DocumentImportError(
            DocumentImportErrorCode.MALFORMED_DOCUMENT,
            "The OpenDocument file has no text body.",
            filename=filename,
        )
    return _join_blocks(_odt_blocks(office_text, styles, lists))


def _odt_text_styles(roots: list[ElementTree.Element]) -> dict[str, tuple[bool, bool]]:
    styles: dict[str, tuple[bool, bool]] = {}
    for root in roots:
        for style in root.iter(f"{_STYLE}style"):
            name = style.get(f"{_STYLE}name", "")
            if not name:
                continue
            properties = style.find(f"{_STYLE}text-properties")
            bold = False
            italic = False
            if properties is not None:
                bold = properties.get(f"{_FO}font-weight", "").lower() == "bold"
                italic = properties.get(f"{_FO}font-style", "").lower() == "italic"
            normalized_name = name.lower().replace("_20_", " ")
            bold = bold or "strong" in normalized_name
            italic = italic or "emphasis" in normalized_name
            styles[name] = (bold, italic)
    return styles


def _odt_list_styles(roots: list[ElementTree.Element]) -> dict[tuple[str, int], bool]:
    styles: dict[tuple[str, int], bool] = {}
    for root in roots:
        for list_style in root.iter(f"{_TEXT}list-style"):
            name = list_style.get(f"{_STYLE}name", "")
            for child in list_style:
                if child.tag not in {
                    f"{_TEXT}list-level-style-number",
                    f"{_TEXT}list-level-style-bullet",
                }:
                    continue
                level = int(child.get(f"{_TEXT}level", "1")) - 1
                styles[(name, level)] = child.tag == f"{_TEXT}list-level-style-number"
    return styles


def _odt_blocks(
    container: ElementTree.Element,
    styles: dict[str, tuple[bool, bool]],
    list_styles: dict[tuple[str, int], bool],
) -> list[str]:
    blocks: list[str] = []
    for child in container:
        if child.tag == f"{_TEXT}h":
            rendered = _odt_inline(child, styles).strip()
            if rendered:
                level = min(max(int(child.get(f"{_TEXT}outline-level", "1")), 1), 6)
                blocks.append(f"{'#' * level} {rendered}")
        elif child.tag == f"{_TEXT}p":
            rendered = _odt_paragraph(child, styles)
            if rendered:
                blocks.append(rendered)
        elif child.tag == f"{_TEXT}list":
            blocks.extend(_odt_list(child, styles, list_styles, level=0, inherited_style=""))
        elif child.tag == f"{_TABLE}table":
            rendered = _odt_table(child, styles)
            if rendered:
                blocks.append(rendered)
        elif child.tag in {f"{_TEXT}section", f"{_OFFICE}text"}:
            blocks.extend(_odt_blocks(child, styles, list_styles))
    return blocks


def _odt_paragraph(
    paragraph: ElementTree.Element,
    styles: dict[str, tuple[bool, bool]],
) -> str:
    rendered = _odt_inline(paragraph, styles).strip()
    if not rendered:
        return ""
    style_name = paragraph.get(f"{_TEXT}style-name", "")
    heading_level = _heading_level(style_name.replace("_20_", " "))
    if heading_level is not None:
        return f"{'#' * heading_level} {rendered}"
    if "quote" in style_name.lower():
        return "> " + rendered.replace("\n", "\n> ")
    return rendered


def _odt_inline(element: ElementTree.Element, styles: dict[str, tuple[bool, bool]]) -> str:
    parts: list[str] = []
    if element.text:
        parts.append(_escape_markdown_inline(element.text))
    for child in element:
        if child.tag == f"{_TEXT}line-break":
            rendered = "\n"
        elif child.tag == f"{_TEXT}tab":
            rendered = "\t"
        elif child.tag == f"{_TEXT}s":
            count = min(max(int(child.get(f"{_TEXT}c", "1")), 1), 100)
            rendered = " " * count
        else:
            rendered = _odt_inline(child, styles)
            if child.tag == f"{_TEXT}span":
                style_name = child.get(f"{_TEXT}style-name", "")
                bold, italic = styles.get(style_name, (False, False))
                rendered = _apply_emphasis(rendered, bold=bold, italic=italic)
        parts.append(rendered)
        if child.tail:
            parts.append(_escape_markdown_inline(child.tail))
    return "".join(parts)


def _odt_list(
    list_element: ElementTree.Element,
    styles: dict[str, tuple[bool, bool]],
    list_styles: dict[tuple[str, int], bool],
    *,
    level: int,
    inherited_style: str,
) -> list[str]:
    blocks: list[str] = []
    style_name = list_element.get(f"{_TEXT}style-name", inherited_style)
    ordered = list_styles.get((style_name, level), False)
    marker = "1." if ordered else "-"
    for item in list_element.findall(f"{_TEXT}list-item"):
        emitted_item = False
        for child in item:
            if child.tag in {f"{_TEXT}p", f"{_TEXT}h"}:
                rendered = _odt_inline(child, styles).strip()
                if rendered:
                    prefix = marker if not emitted_item else "  "
                    blocks.append(f"{'  ' * level}{prefix} {rendered}")
                    emitted_item = True
            elif child.tag == f"{_TEXT}list":
                blocks.extend(
                    _odt_list(
                        child,
                        styles,
                        list_styles,
                        level=level + 1,
                        inherited_style=style_name,
                    )
                )
    return blocks


def _odt_table(table: ElementTree.Element, styles: dict[str, tuple[bool, bool]]) -> str:
    rows: list[list[str]] = []
    for row in table.findall(f"{_TABLE}table-row"):
        cells: list[str] = []
        for cell in row.findall(f"{_TABLE}table-cell"):
            paragraphs = [
                _odt_inline(paragraph, styles).strip() for paragraph in cell.findall(f"{_TEXT}p")
            ]
            cell_text = "<br>".join(part for part in paragraphs if part)
            cells.append(cell_text.replace("|", "\\|"))
        if cells:
            rows.append(cells)
    return _markdown_table(rows)


def _convert_legacy_doc(
    content: bytes,
    filename: str,
    *,
    max_expanded_bytes: int,
    soffice_path: str | os.PathLike[str] | None,
    timeout_seconds: float,
) -> bytes:
    executable = _resolve_soffice(soffice_path, filename)
    with tempfile.TemporaryDirectory(prefix="splicr-doc-import-") as temporary_directory:
        root = Path(temporary_directory)
        source_path = root / "source.doc"
        output_directory = root / "converted"
        profile_directory = root / "libreoffice-profile"
        output_directory.mkdir()
        profile_directory.mkdir()
        source_path.write_bytes(content)

        command = [
            executable,
            "--headless",
            f"-env:UserInstallation={profile_directory.as_uri()}",
            "--convert-to",
            "docx",
            "--outdir",
            str(output_directory),
            str(source_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            detail = "timed out" if isinstance(error, subprocess.TimeoutExpired) else str(error)
            raise DocumentImportError(
                DocumentImportErrorCode.CONVERSION_FAILED,
                f"LibreOffice could not convert the legacy .doc file: {detail}.",
                filename=filename,
            ) from error

        output_path = output_directory / "source.docx"
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or result.stdout or "no conversion output").strip()[:500]
            raise DocumentImportError(
                DocumentImportErrorCode.CONVERSION_FAILED,
                f"LibreOffice could not convert the legacy .doc file: {detail}.",
                filename=filename,
            )
        output_size = output_path.stat().st_size
        if output_size > max_expanded_bytes:
            raise DocumentImportError(
                DocumentImportErrorCode.EXPANDED_FILE_TOO_LARGE,
                (
                    f"Converted document is {output_size} bytes; the expanded-file limit is "
                    f"{max_expanded_bytes} bytes."
                ),
                filename=filename,
            )
        return output_path.read_bytes()


def _resolve_soffice(
    configured_path: str | os.PathLike[str] | None,
    filename: str,
) -> str:
    if configured_path is not None:
        configured = os.fspath(configured_path)
        resolved = shutil.which(configured)
        if resolved is None and Path(configured).is_file():
            resolved = str(Path(configured))
        if resolved is not None:
            return resolved
        raise DocumentImportError(
            DocumentImportErrorCode.CONVERTER_UNAVAILABLE,
            f"Configured LibreOffice executable was not found: {configured}.",
            filename=filename,
        )

    for command in ("soffice", "libreoffice"):
        resolved = shutil.which(command)
        if resolved is not None:
            return resolved

    candidates = []
    for environment_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        program_files = os.environ.get(environment_name)
        if program_files:
            candidates.append(Path(program_files) / "LibreOffice" / "program" / "soffice.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    raise DocumentImportError(
        DocumentImportErrorCode.CONVERTER_UNAVAILABLE,
        (
            "Legacy .doc import requires LibreOffice. Install LibreOffice or configure the path "
            "to soffice; .docx, .odt, Markdown, text, and JSON do not require it."
        ),
        filename=filename,
    )


def _heading_level(style_name: str) -> int | None:
    normalized = re.sub(r"[\s_-]+", "", style_name).lower()
    if normalized in {"title", "documenttitle"}:
        return 1
    match = re.search(r"heading([1-6])$", normalized)
    if match:
        return int(match.group(1))
    return None


def _apply_emphasis(
    text: str,
    *,
    bold: bool,
    italic: bool,
    strike: bool = False,
) -> str:
    if not text or not (bold or italic or strike):
        return text
    match = re.fullmatch(r"(\s*)(.*?)(\s*)", text, flags=re.DOTALL)
    if match is None or not match.group(2):
        return text
    leading, core, trailing = match.groups()
    if bold and italic:
        core = f"***{core}***"
    elif bold:
        core = f"**{core}**"
    elif italic:
        core = f"*{core}*"
    if strike:
        core = f"~~{core}~~"
    return f"{leading}{core}{trailing}"


def _escape_markdown_inline(text: str) -> str:
    return re.sub(r"([\\`*_])", r"\\\1", text)


def _markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(row) + " |" for row in normalized]
    lines.insert(1, "| " + " | ".join("---" for _ in range(width)) + " |")
    return "\n".join(lines)


def _join_blocks(blocks: list[str]) -> str:
    if not blocks:
        return ""
    output = blocks[0]
    previous_was_list = _is_markdown_list_block(blocks[0])
    for block in blocks[1:]:
        is_list = _is_markdown_list_block(block)
        output += ("\n" if previous_was_list and is_list else "\n\n") + block
        previous_was_list = is_list
    return output


def _is_markdown_list_block(block: str) -> bool:
    return re.match(r"^\s*(?:-|\d+\.)\s+", block) is not None


def _normalize_markdown(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.removeprefix("\ufeff").strip("\n")
    return re.sub(r"\n{3,}", "\n\n", normalized)


def _infer_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip().strip("*_`~")
            if title:
                return title[:200]
    return None
