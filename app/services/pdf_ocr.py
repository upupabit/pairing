"""Text from a scanned (image-only) PDF, for the knowledge base: pages rendered by pdftoppm (poppler-utils),
read by the tesseract program (tesseract-ocr). Optional: without them a scanned PDF is reported, not read.
Blocking and slow (seconds per page), so callers run it in a thread.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("llama_chat")


class PdfOcr:
    MAX_PAGES = int(os.environ.get("KNOWLEDGE_OCR_MAX_PAGES", "100"))
    DPI = 200
    PAGE_TIMEOUT_SECONDS = 120
    MISSING = "a scanned PDF: install tesseract-ocr (and poppler-utils) on this server to read it"

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))

    @staticmethod
    def languages() -> str:
        """KNOWLEDGE_OCR_LANGS (e.g. "eng+heb"), else every language installed (`tesseract --list-langs`)."""
        if wanted := os.environ.get("KNOWLEDGE_OCR_LANGS"):
            return wanted
        try:
            listed = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return "eng"
        langs = [line.strip() for line in listed.splitlines()[1:] if line.strip() and line.strip() != "osd"]
        return "+".join(langs) or "eng"

    def text(self, raw: bytes) -> str:
        """The PDF's text, page by page; empty when nothing was read."""
        langs = self.languages()
        with tempfile.TemporaryDirectory(prefix="pairing-ocr-") as folder:
            pdf = Path(folder) / "in.pdf"
            pdf.write_bytes(raw)
            render = ["pdftoppm", "-r", str(self.DPI), "-png", "-l", str(self.MAX_PAGES), str(pdf), f"{folder}/page"]
            subprocess.run(render, check=True, capture_output=True, timeout=self.PAGE_TIMEOUT_SECONDS * 4)
            pages = []
            for image in sorted(Path(folder).glob("page*.png")):
                done = subprocess.run(
                    ["tesseract", str(image), "stdout", "-l", langs],
                    capture_output=True,
                    text=True,
                    timeout=self.PAGE_TIMEOUT_SECONDS,
                )
                pages.append(done.stdout.strip())
        return "\n\n".join(p for p in pages if p)
