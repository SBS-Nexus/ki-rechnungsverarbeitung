#!/usr/bin/env python3
"""
KI-Rechnungsverarbeitung - OCR Module v3.1
OCR fallback for scanned PDFs using Tesseract
"""

import logging
from pathlib import Path
from typing import Optional
from PIL import Image
import io

try:
    import pytesseract
    from pdf2image import convert_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Process scanned PDFs with OCR"""
    
    def __init__(self, language: str = 'deu', config: dict = None):
        """
        Initialize OCR Processor
        
        Args:
            language: Tesseract language (deu, eng, fra, etc.)
            config: OCR configuration options
        """
        if not OCR_AVAILABLE:
            raise ImportError(
                "OCR dependencies not installed!\n"
                "Install with: pip install pytesseract pdf2image pillow\n"
                "Also install Tesseract: brew install tesseract (Mac) or apt-get install tesseract-ocr (Linux)"
            )
        
        self.language = language
        self.config = config or {}
        
        # Tesseract configuration
        self.tesseract_config = '--oem 3 --psm 6'  # LSTM + Assume uniform block of text
        
        # Check if Tesseract is installed
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            raise RuntimeError(f"Tesseract not found! Please install Tesseract OCR. Error: {e}")
    
    def extract_text_from_scanned_pdf(self, pdf_path: Path) -> Optional[str]:
        """
        Extract text from scanned PDF using OCR
        
        Args:
            pdf_path: Path to scanned PDF
            
        Returns:
            Extracted text or None if failed
        """
        try:
            logger.info(f"Starting OCR for: {pdf_path.name}")
            
            # Convert PDF to images
            images = convert_from_path(
                str(pdf_path),
                dpi=300,  # High DPI for better OCR accuracy
                fmt='jpeg',
                thread_count=2
            )
            
            logger.info(f"Converted PDF to {len(images)} images")
            
            # Process each page
            full_text = ""
            for i, image in enumerate(images, 1):
                logger.info(f"Processing page {i}/{len(images)}")
                
                # Preprocess image for better OCR
                processed_image = self._preprocess_image(image)
                
                # Perform OCR
                page_text = pytesseract.image_to_string(
                    processed_image,
                    lang=self.language,
                    config=self.tesseract_config
                )
                
                full_text += page_text + "\n\n"
            
            if not full_text.strip():
                logger.warning(f"No text extracted from {pdf_path.name}")
                return None
            
            logger.info(f"OCR completed: {len(full_text)} characters extracted")
            return full_text
            
        except Exception as e:
            logger.error(f"OCR failed for {pdf_path.name}: {e}")
            return None
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image for better OCR accuracy
        
        Improvements:
        - Convert to grayscale
        - Increase contrast
        - Denoise (optional)
        """
        # Convert to grayscale
        image = image.convert('L')
        
        # Increase contrast (simple threshold)
        # This helps with low-quality scans
        threshold = 128
        image = image.point(lambda p: 255 if p > threshold else 0)
        
        return image
    
    def is_scanned_pdf(self, pdf_path: Path) -> bool:
        """
        Check if PDF is likely scanned (image-based)
        
        Simple heuristic: If normal text extraction yields very little text,
        it's probably scanned
        
        Args:
            pdf_path: Path to PDF
            
        Returns:
            True if likely scanned, False otherwise
        """
        try:
            import pypdf
            
            with open(pdf_path, 'rb') as file:
                reader = pypdf.PdfReader(file)
                
                # Sample first page
                if len(reader.pages) > 0:
                    text = reader.pages[0].extract_text()
                    
                    # If very little text extracted, likely scanned
                    if len(text.strip()) < 50:
                        logger.info(f"{pdf_path.name} appears to be scanned (< 50 chars)")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"Could not check if PDF is scanned: {e}")
            return False
    
    def extract_with_fallback(self, pdf_path: Path, normal_text: Optional[str]) -> Optional[str]:
        """
        Try normal extraction first, fall back to OCR if needed
        
        Args:
            pdf_path: Path to PDF
            normal_text: Text from normal PDF extraction (or None if failed)
            
        Returns:
            Extracted text (normal or OCR)
        """
        # If normal extraction worked and has substantial text, use it
        if normal_text and len(normal_text.strip()) > 100:
            logger.info(f"Using normal text extraction for {pdf_path.name}")
            return normal_text
        
        # Check if it's a scanned PDF
        if self.is_scanned_pdf(pdf_path):
            logger.info(f"Falling back to OCR for {pdf_path.name}")
            return self.extract_text_from_scanned_pdf(pdf_path)
        
        # Not scanned, but extraction failed for other reasons
        logger.warning(f"PDF is not scanned, but extraction failed: {pdf_path.name}")
        return normal_text


class OCRConfig:
    """OCR Configuration manager"""
    
    SUPPORTED_LANGUAGES = {
        'deu': 'Deutsch',
        'eng': 'English',
        'fra': 'Français',
        'spa': 'Español',
        'ita': 'Italiano',
        'deu+eng': 'Deutsch + English'
    }
    
    @staticmethod
    def get_default_config() -> dict:
        """Get default OCR configuration"""
        return {
            'language': 'deu',
            'dpi': 300,
            'preprocess': True,
            'denoise': False,
            'threshold': 128
        }
    
    @staticmethod
    def check_dependencies() -> dict:
        """Check if OCR dependencies are installed"""
        status = {
            'pytesseract': False,
            'pdf2image': False,
            'tesseract_binary': False,
            'all_available': False
        }
        
        try:
            import pytesseract
            status['pytesseract'] = True
            
            # Check Tesseract binary
            pytesseract.get_tesseract_version()
            status['tesseract_binary'] = True
            
        except ImportError:
            pass
        except Exception:
            pass
        
        try:
            import pdf2image
            status['pdf2image'] = True
        except ImportError:
            pass
        
        status['all_available'] = all([
            status['pytesseract'],
            status['pdf2image'],
            status['tesseract_binary']
        ])
        
        return status


def extract_text_with_ocr_fallback(pdf_path: Path, normal_text: Optional[str] = None) -> Optional[str]:
    """
    Convenience function for OCR fallback
    
    Usage:
        from ocr_processor import extract_text_with_ocr_fallback
        text = extract_text_with_ocr_fallback(pdf_path, normal_text)
    
    Args:
        pdf_path: Path to PDF
        normal_text: Text from normal extraction (optional)
        
    Returns:
        Extracted text or None
    """
    if not OCR_AVAILABLE:
        logger.warning("OCR not available - returning normal text")
        return normal_text
    
    try:
        processor = OCRProcessor()
        return processor.extract_with_fallback(pdf_path, normal_text)
    except Exception as e:
        logger.error(f"OCR processing failed: {e}")
        return normal_text


# Installation instructions
INSTALLATION_GUIDE = """
═══════════════════════════════════════════════════════════════
  OCR-MODUL INSTALLATION
═══════════════════════════════════════════════════════════════

Schritt 1: Python-Packages installieren
─────────────────────────────────────────
pip install pytesseract pdf2image pillow

Schritt 2: Tesseract OCR installieren
─────────────────────────────────────────
Mac:
  brew install tesseract
  brew install tesseract-lang  # Für Deutsch

Linux (Ubuntu/Debian):
  sudo apt-get update
  sudo apt-get install tesseract-ocr
  sudo apt-get install tesseract-ocr-deu  # Für Deutsch

Windows:
  1. Download: https://github.com/UB-Mannheim/tesseract/wiki
  2. Installieren
  3. Pfad zu Environment Variables hinzufügen

Schritt 3: Poppler installieren (für pdf2image)
─────────────────────────────────────────
Mac:
  brew install poppler

Linux:
  sudo apt-get install poppler-utils

Windows:
  Download: http://blog.alivate.com.au/poppler-windows/
  Pfad zu Environment Variables hinzufügen

Schritt 4: Testen
─────────────────────────────────────────
python -c "from ocr_processor import OCRConfig; print(OCRConfig.check_dependencies())"

Sollte zeigen: {'all_available': True, ...}

═══════════════════════════════════════════════════════════════
  NUTZUNG
═══════════════════════════════════════════════════════════════

In config.yaml aktivieren:
───────────────────────────
features:
  ocr_fallback: true

OCR wird automatisch genutzt wenn:
- PDF ist gescannt (Bild-basiert)
- Normale Textextraktion < 100 Zeichen

═══════════════════════════════════════════════════════════════
"""

if __name__ == "__main__":
    # Print installation guide
    print(INSTALLATION_GUIDE)
    
    # Check dependencies
    status = OCRConfig.check_dependencies()
    print("\n📊 Dependency Status:")
    print(f"  pytesseract: {'✅' if status['pytesseract'] else '❌'}")
    print(f"  pdf2image: {'✅' if status['pdf2image'] else '❌'}")
    print(f"  tesseract: {'✅' if status['tesseract_binary'] else '❌'}")
    print(f"\n  OCR Available: {'✅ YES' if status['all_available'] else '❌ NO'}")
