#!/usr/bin/env python3
"""
Core invoice processing logic with Hybrid AI
Nutzt llm_router mit Expert-Level Prompts
"""
import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import pypdf
import pdfplumber
import pytesseract
from ocr_optimizer import ocr_with_fallback, extract_from_pdf_optimized, detect_scan_quality
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
from pdf2image import convert_from_path
from PIL import Image
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Config:
    """Configuration management"""
    
    def __init__(self, config_file: str = 'config.yaml'):
        self.config_file = Path(config_file)
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load configuration from YAML file"""
        if not self.config_file.exists():
            return self._default_config()
        
        try:
            import yaml
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config: {e}")
            return self._default_config()
    
    def _default_config(self) -> dict:
        """Return default configuration"""
        return {
            'ai': {
                'mode': 'hybrid',
                'complexity_threshold': 20
            }
        }
    
    def get(self, key: str, default=None):
        """Get config value by dot notation key"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default


class ComplexityAnalyzer:
    """Analyzes PDF complexity to determine which AI model to use"""
    
    @staticmethod
    def analyze_complexity(text: str, pdf_path: Path) -> Tuple[str, int]:
        """
        Analyze document complexity and return (model_to_use, complexity_score)
        
        Returns:
            Tuple[str, int]: ('gpt-4o' or 'claude', complexity_score 0-100)
        """
        complexity_score = 0
        
        # 1. MEHRERE SEITEN (+10)
        try:
            with open(pdf_path, 'rb') as f:
                pdf = pypdf.PdfReader(f)
                pages = len(pdf.pages)
                if pages > 1:
                    complexity_score += 10
                if pages > 3:
                    complexity_score += 5
        except Exception:
            pass
        
        # 2. VIEL TEXT (+15)
        text_length = len(text)
        if text_length > 2000:
            complexity_score += 15
        elif text_length > 1000:
            complexity_score += 8
        elif text_length < 200:
            complexity_score += 5
        
        # 3. TABELLEN ERKANNT (+10)
        table_patterns = [
            r'\d+[\.,]\d+.*\d+[\.,]\d+.*\d+[\.,]\d+',
            r'(?:\d+\s+){4,}',
            r'\|.*\|.*\|',
        ]
        table_matches = sum(len(re.findall(pattern, text)) for pattern in table_patterns)
        
        if table_matches > 10:
            complexity_score += 10
        elif table_matches > 5:
            complexity_score += 5
        
        # 4. SCHLECHTE PDF-QUALITÄT (+15)
        quality_issues = 0
        single_chars = len(re.findall(r'\b\w\b', text))
        if single_chars > 30:
            quality_issues += 1
        
        special_char_ratio = len(re.findall(r'[^a-zA-Z0-9\s\.,€$äöüÄÖÜß-]', text)) / max(len(text), 1)
        if special_char_ratio > 0.1:
            quality_issues += 1
        
        if len(re.findall(r'[a-z][A-Z]', text)) > 10:
            quality_issues += 1
        
        if quality_issues >= 2:
            complexity_score += 15
        elif quality_issues >= 1:
            complexity_score += 8
        
        # 5. HANDSCHRIFT/SCAN (+20)
        try:
            file_size = pdf_path.stat().st_size
            if text_length < 300 and file_size > 500000:
                complexity_score += 20
            elif text_length < 500 and file_size > 1000000:
                complexity_score += 15
            if file_size > 5000000:
                complexity_score += 5
        except Exception:
            pass
        
        # Maximal 100
        complexity_score = min(complexity_score, 100)
        
        # Decision
        from invoice_core import Config
        config = Config()
        threshold = config.get('ai.complexity_threshold', 20)
        
        if complexity_score >= threshold:
            model = 'claude'
        else:
            model = 'gpt-4o'
        
        return model, complexity_score


class InvoiceProcessor:
    """Process invoices with Hybrid AI using Expert-Level Prompts"""
    
    def __init__(self, config: Config):
        self.config = config
        
        # Initialize LLM Router
        try:
            import llm_router
            self.llm_router = llm_router
            logger.info("✅ LLM Router initialized")
        except Exception as e:
            logger.error(f"Failed to initialize LLM Router: {e}")
            raise
    
    def process_invoice(self, pdf_path: Path) -> Optional[dict]:
        """
        Process a single invoice with Hybrid AI and Expert Prompts
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            dict with extracted data or None on error
        """
        try:
            print(f"📄 {pdf_path.name}")
            
            # Extract text from PDF
            text = extract_text_from_pdf(pdf_path)
            if not text or len(text) < 50:
                print(f"   ❌ Fehler: Kein Text extrahiert")
                return None
            
            # Calculate complexity
            complexity_score = ComplexityAnalyzer.analyze_complexity(text, pdf_path)[1]
            
            # Select model based on complexity
            provider, model = self.llm_router.pick_provider_model(complexity_score)
            
            print(f"   Komplexität: {complexity_score}/100")
            print(f"   Modell: {'🚀 GPT-4o' if provider == 'openai' else '🎯 Claude Sonnet 4.5'}")
            
            # Extract data with Expert-Level Prompts from llm_router
            try:
                data = self.llm_router.extract_invoice_data_with_fallback(text, str(pdf_path), provider, model)
                
                if not data:
                    print(f"   ❌ Keine Daten extrahiert")
                    return None
                
                # Add metadata
                data['dateiname'] = pdf_path.name
                data['pdf_filename'] = pdf_path.name
                data['ai_model_used'] = 'claude' if provider == 'anthropic' else 'gpt-4o'
                data['complexity_score'] = complexity_score
                data['processed_at'] = datetime.now().isoformat()
                
                betrag = data.get('betrag_brutto', 0)
                if isinstance(betrag, str):
                    betrag = 0
                print(f"   ✅ Erfolgreich: {betrag:.2f}€")
                
                return data
                
            except Exception as e:
                print(f"   ❌ AI extraction error: {e}")
                logger.error(f"AI extraction failed for {pdf_path.name}: {e}")
                return None
                
        except Exception as e:
            print(f"   ❌ Processing error: {e}")
            logger.error(f"Failed to process {pdf_path.name}: {e}")
            return None
    
def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from PDF using hybrid approach:
    1. pdfplumber for main text
    2. OCR for footer/images
    """
    text = ""
    
    # METHODE 1: pdfplumber (schnell, für Haupttext)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        logger.info(f"pdfplumber extracted {len(text)} chars")
    except Exception as e:
        logger.error(f"pdfplumber failed: {e}")
    
    # METHODE 2: OCR (langsam aber findet ALLES, auch Bilder/Footer)
    try:
        # PDF zu Bildern konvertieren
        images = convert_from_path(pdf_path, dpi=300, poppler_path='/usr/bin')
        
        ocr_text = ""
        for i, image in enumerate(images):
            # OCR auf jede Seite anwenden
            # Optimierte OCR mit Fallback
            result = ocr_with_fallback(image)
            page_ocr = result.get("text", "")
            logger.info(f"OCR Seite {i+1}: {result.get("confidence", 0)*100:.0f}% Konfidenz, Methode: {result.get("method", "unknown")}")
            ocr_text += page_ocr + "\n"
        
        logger.info(f"OCR extracted {len(ocr_text)} chars")
        
        # Kombiniere pdfplumber + OCR Text
        # OCR hat oft mehr (findet Footer), also bevorzugen wenn länger
        if len(ocr_text) > len(text):
            text = ocr_text
            logger.info("Using OCR text (longer/more complete)")
        else:
            # Oder füge Footer aus OCR an pdfplumber Text an
            # Nimm die letzten 500 Zeichen aus OCR (Footer)
            footer = ocr_text[-500:] if len(ocr_text) > 500 else ocr_text
            text += "\n\n=== OCR FOOTER ===\n" + footer
            logger.info("Appended OCR footer to pdfplumber text")
            
    except Exception as e:
        logger.error(f"OCR failed: {e}")
    
    # Fallback: pypdf
    if not text.strip():
        logger.warning("Both pdfplumber and OCR failed, trying pypdf")
        try:
            with open(pdf_path, 'rb') as f:
                pdf_reader = pypdf.PdfReader(f)
                for page in pdf_reader.pages:
                    text += page.extract_text() or ""
        except Exception as e:
            logger.error(f"pypdf also failed: {e}")
    
    return text

def get_pdf_files(directory: str) -> List[Path]:
    """Get all PDF files from directory"""
    path = Path(directory)
    if not path.exists():
        return []
    return sorted(path.glob("*.pdf"))
def get_pdf_files(directory: str) -> List[Path]:
    """Get all PDF files from directory"""
    path = Path(directory)
    if not path.exists():
        return []
    return sorted(path.glob("*.pdf"))


def calculate_statistics(results: List[dict]) -> dict:
    """Calculate statistics from results"""
    if not results:
        return {
            'total_brutto': 0,
            'total_netto': 0,
            'total_mwst': 0,
            'average_brutto': 0,
            'count': 0
        }
    
# Sichere Konvertierung zu float
    total_brutto = sum(
        float(r.get('betrag_brutto', 0)) if r.get('betrag_brutto') and str(r.get('betrag_brutto')).strip() else 0 
        for r in results
    )
    total_netto = sum(
        float(r.get('betrag_netto', 0)) if r.get('betrag_netto') and str(r.get('betrag_netto')).strip() else 0
        for r in results
    )
    total_mwst = sum(
        float(r.get('mwst_betrag', 0)) if r.get('mwst_betrag') and str(r.get('mwst_betrag')).strip() else 0
        for r in results
    )    
    return {
        'total_brutto': total_brutto,
        'total_netto': total_netto,
        'total_mwst': total_mwst,
        'average_brutto': total_brutto / len(results) if results else 0,
        'count': len(results)
    }

# === Plausibility Integration ===
def run_plausibility_for_invoice(invoice_id: int):
    """Führe Plausibilitätsprüfung nach Invoice-Speicherung aus"""
    try:
        from plausibility import run_plausibility_checks, save_plausibility_check
        
        checks = run_plausibility_checks(invoice_id)
        
        for check in checks:
            save_plausibility_check(invoice_id, check)
            logger.info(f"⚠️ Plausibility: {check['check_type']} ({check['severity']}) für Invoice {invoice_id}")
        
        return len(checks)
    except Exception as e:
        logger.error(f"❌ Plausibility check failed for invoice {invoice_id}: {e}")
        return 0

