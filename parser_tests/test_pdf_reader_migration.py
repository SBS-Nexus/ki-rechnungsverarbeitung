"""PDF reader migration regressions using synthetic documents only."""
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pypdf
from reportlab.pdfgen import canvas

from invoice_core import ComplexityAnalyzer
from ocr_processor import OCRProcessor


class PdfReaderMigrationTests(unittest.TestCase):
    def make_pdf(self, path, pages=1, text="Synthetic invoice with enough ordinary text for scan detection."):
        buffer = io.BytesIO()
        document = canvas.Canvas(buffer)
        for _ in range(pages):
            document.drawString(72, 720, text)
            document.showPage()
        document.save()
        path.write_bytes(buffer.getvalue())

    def test_pdf_text_pages_and_scan_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.pdf"
            self.make_pdf(path, pages=2)
            reader = pypdf.PdfReader(path)
            self.assertEqual(len(reader.pages), 2)
            self.assertIn("Synthetic invoice", reader.pages[0].extract_text())
            # Scan classification only reads PDF text; it does not need an OCR binary.
            processor = OCRProcessor.__new__(OCRProcessor)
            self.assertFalse(processor.is_scanned_pdf(path))
            self.make_pdf(path, text="")
            self.assertTrue(processor.is_scanned_pdf(path))

    def test_complexity_analyzer_preserves_page_count_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            one = Path(directory) / "one.pdf"
            two = Path(directory) / "two.pdf"
            self.make_pdf(one)
            self.make_pdf(two, pages=2)
            text = "Synthetic invoice text " * 15
            _, one_score = ComplexityAnalyzer.analyze_complexity(text, one)
            _, two_score = ComplexityAnalyzer.analyze_complexity(text, two)
            self.assertEqual(two_score - one_score, 10)

    def test_unterminated_pdf_comment_finishes_with_an_error(self):
        code = """
from io import BytesIO
from pypdf.generic import read_object
from pypdf.errors import PdfReadError
try:
    read_object(BytesIO(b"% synthetic unterminated comment"), None)
except PdfReadError:
    pass
else:
    raise AssertionError("Expected a PDF parse error")
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
