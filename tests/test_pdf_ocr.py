"""Scanned PDFs in the knowledge base (services/pdf_ocr.py, document_sync.py)."""

import subprocess
from pathlib import Path

import pytest

from app.services import document_sync, pdf_ocr
from app.services.pdf_ocr import PdfOcr


def _fake_run(calls):
    def run(cmd, **_kw):
        calls.append(cmd[0])
        if cmd[:2] == ["tesseract", "--list-langs"]:
            return subprocess.CompletedProcess(cmd, 0, "List of available languages (3):\neng\nheb\nosd\n", "")
        if cmd[0] == "pdftoppm":
            out = Path(cmd[-1])
            for n in (1, 2):
                Path(f"{out}-{n}.png").write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, f"text of {Path(cmd[1]).name}\n", "")

    return run


def test_reads_every_page_with_the_installed_languages(monkeypatch):
    calls = []
    monkeypatch.setattr(pdf_ocr.subprocess, "run", _fake_run(calls))
    monkeypatch.delenv("KNOWLEDGE_OCR_LANGS", raising=False)

    assert PdfOcr.languages() == "eng+heb"
    assert PdfOcr().text(b"%PDF") == "text of page-1.png\n\ntext of page-2.png"
    assert calls.count("pdftoppm") == 1


def test_languages_can_be_set(monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_OCR_LANGS", "heb")
    assert PdfOcr.languages() == "heb"


@pytest.mark.asyncio
async def test_a_scanned_pdf_is_read_or_reported(db, tmp_path, monkeypatch):
    folder = tmp_path / "global"
    folder.mkdir()
    (folder / "scan.pdf").write_bytes(b"%PDF scanned")
    monkeypatch.setattr(document_sync, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(document_sync, "extract_text", lambda _raw, _suffix: "")

    async def model(_db):
        return "embed-model"

    monkeypatch.setattr(document_sync.model_catalog_service, "get_default_embedding_model", model)

    monkeypatch.setattr(PdfOcr, "available", staticmethod(lambda: False))
    stats = await document_sync._drain_sync_stats(folder, None, db)
    assert "install tesseract-ocr" in stats["errors"][0]

    monkeypatch.setattr(PdfOcr, "available", staticmethod(lambda: True))
    monkeypatch.setattr(PdfOcr, "text", lambda _self, _raw: "")
    stats = await document_sync._drain_sync_stats(folder, None, db)
    assert "empty file" in stats["errors"][0]  # tried, nothing on the pages
