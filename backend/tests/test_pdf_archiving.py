from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.archiver import SingleFileArchiver, YtDlpDownloader
from app.core.config import Settings
from app.semantic import SemanticDocumentPreparer, extract_readable_text
from app.service import ArchiveTaskService


@pytest.fixture
def document_copy_single_file(tmp_path: Path) -> Path:
    script = tmp_path / "single-file-document-copy"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import shutil
import sys
from urllib.parse import unquote, urlparse

source = pathlib.Path(unquote(urlparse(sys.argv[1]).path))
output = pathlib.Path(sys.argv[2])
document_option = next(
    value for value in sys.argv if value.startswith("--browser-document-file=")
)
document = pathlib.Path(document_option.split("=", 1)[1])
shutil.copyfile(source, document)
content_type = "application/pdf" if "claimed-pdf" in source.name else "application/octet-stream"
document.with_name(document.name + ".json").write_text(
    '{"status": 200, "contentType": "' + content_type + '"}',
    encoding="utf-8",
)
output.write_text(
    "<html><head><title>Saved page</title></head><body>saved page</body></html>",
    encoding="utf-8",
)
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def make_settings(tmp_path: Path, single_file_path: Path) -> Settings:
    return Settings(
        archive_dir=tmp_path / "archive",
        browser_profile_dir=tmp_path / "profile",
        single_file_path=str(single_file_path),
        use_xvfb=False,
        semantic_search_enabled=False,
    )


def write_pdf(path: Path, *, text: str | None = None, password: str | None = None) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}  # noqa: SLF001
                )
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    if password:
        writer.encrypt(password)
    with path.open("wb") as handle:
        writer.write(handle)


def test_archiver_promotes_valid_pdf_without_using_url_suffix(
    tmp_path: Path,
    document_copy_single_file: Path,
) -> None:
    source = tmp_path / "download-without-extension"
    write_pdf(source)
    settings = make_settings(tmp_path, document_copy_single_file)

    artifact = asyncio.run(
        SingleFileArchiver(settings).archive(source.as_uri(), "task.html")
    )

    assert artifact.file_name == "task.pdf"
    assert artifact.media_type == "application/pdf"
    assert artifact.page_count == 1
    assert (settings.archive_dir / "task.pdf").read_bytes() == source.read_bytes()
    assert not (settings.archive_dir / "task.html").exists()
    assert not list(settings.archive_dir.glob("*.tmp*"))


def test_archiver_keeps_normal_html_flow(
    tmp_path: Path,
    document_copy_single_file: Path,
) -> None:
    source = tmp_path / "page.html"
    source.write_text("<html><body>live page</body></html>", encoding="utf-8")
    settings = make_settings(tmp_path, document_copy_single_file)

    artifact = asyncio.run(
        SingleFileArchiver(settings).archive(source.as_uri(), "task.html")
    )

    assert artifact.file_name == "task.html"
    assert artifact.media_type == "text/html"
    assert "saved page" in (settings.archive_dir / "task.html").read_text(encoding="utf-8")
    assert not list(settings.archive_dir.glob("*.tmp*"))


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("truncated.bin", b"%PDF-1.7\ntruncated"),
        ("claimed-pdf-login.html", b"<html><body>please log in</body></html>"),
        ("claimed-pdf-empty.bin", b""),
    ],
)
def test_archiver_rejects_invalid_pdf_responses_and_cleans_files(
    tmp_path: Path,
    document_copy_single_file: Path,
    name: str,
    payload: bytes,
) -> None:
    source = tmp_path / name
    source.write_bytes(payload)
    settings = make_settings(tmp_path, document_copy_single_file)

    with pytest.raises(RuntimeError, match="invalid PDF"):
        asyncio.run(SingleFileArchiver(settings).archive(source.as_uri(), "task.html"))

    assert not list(settings.archive_dir.iterdir())


def test_pdf_text_extraction_and_blank_pdf_skip(tmp_path: Path) -> None:
    text_pdf = tmp_path / "text.pdf"
    blank_pdf = tmp_path / "blank.pdf"
    write_pdf(text_pdf, text="Reader searchable PDF")
    write_pdf(blank_pdf)

    assert "Reader searchable PDF" in (extract_readable_text(text_pdf) or "")
    assert extract_readable_text(blank_pdf) is None

    preparer = SemanticDocumentPreparer(min_chars=1, max_chars=1000, overlap_chars=50)
    prepared = preparer.prepare(text_pdf)
    assert prepared is not None
    assert prepared.chunks == ["Reader searchable PDF"]
    assert preparer.prepare(blank_pdf) is None


def test_archiver_preserves_password_protected_pdf_and_skips_text(
    tmp_path: Path,
    document_copy_single_file: Path,
) -> None:
    source = tmp_path / "protected-document"
    write_pdf(source, text="secret text", password="reader-password")
    settings = make_settings(tmp_path, document_copy_single_file)

    artifact = asyncio.run(
        SingleFileArchiver(settings).archive(source.as_uri(), "task.html")
    )

    assert artifact.file_name == "task.pdf"
    assert artifact.media_type == "application/pdf"
    assert artifact.page_count is None
    assert (settings.archive_dir / "task.pdf").read_bytes() == source.read_bytes()
    assert extract_readable_text(settings.archive_dir / "task.pdf") is None
    assert not list(settings.archive_dir.glob("*.tmp*"))


def test_archive_error_redacts_session_identifiers_and_query_tokens() -> None:
    message = (
        "failed http://example.test/file;jsessionid=secret-session"
        "?resId=45131&token=secret-token&sessionid=secret-query"
    )

    cleaned = ArchiveTaskService._short_error(object(), message)  # type: ignore[arg-type]

    assert "secret-session" not in cleaned
    assert "secret-token" not in cleaned
    assert "secret-query" not in cleaned
    assert ";jsessionid=[已隐藏]" in cleaned


@pytest.mark.parametrize(("tail", "expected"), [("sys.exit(2)", "SingleFile failed"), ("time.sleep(30)", "timed out")])
def test_pdf_capture_process_failure_cleans_partial_files(
    tmp_path: Path,
    tail: str,
    expected: str,
) -> None:
    script = tmp_path / "single-file-interrupted"
    script.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys
import time

output = pathlib.Path(sys.argv[2])
document_option = next(
    value for value in sys.argv if value.startswith("--browser-document-file=")
)
document = pathlib.Path(document_option.split("=", 1)[1])
document.write_bytes(b"%PDF-1.7\\npartial")
document.with_name(document.name + ".json").write_text(
    '{"status": 200, "contentType": "application/pdf"}',
    encoding="utf-8",
)
output.write_text("<html><body>partial</body></html>", encoding="utf-8")
"""
        + tail
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    settings = make_settings(tmp_path, script)
    settings.archive_timeout_seconds = 1

    with pytest.raises(RuntimeError, match=expected):
        asyncio.run(SingleFileArchiver(settings).archive("https://example.test/file", "task.html"))

    assert not list(settings.archive_dir.iterdir())


def test_video_failure_cleanup_preserves_page_archive_files(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, tmp_path / "unused-single-file")
    archive_dir = settings.archive_dir
    archive_dir.mkdir(parents=True)
    preserved_names = {
        "task.html",
        "task.pdf",
        "task.document.tmp",
        "task.document.tmp.json",
        "task.upload-user-file.pdf",
    }
    for name in {*preserved_names, "task.mp4", "task.info.json"}:
        (archive_dir / name).write_bytes(b"test")

    YtDlpDownloader(settings)._remove_created_files(archive_dir, "task", set())

    assert {path.name for path in archive_dir.iterdir()} == preserved_names
