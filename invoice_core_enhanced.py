"""
Enhanced Invoice Processing with Multi-Language Support
"""
from language_detection import detect_language, get_extraction_prompt

def extract_invoice_with_language(pdf_path: str, filename: str):
    """
    Extract invoice with automatic language detection
    """
    from invoice_core import extract_from_pdf
    import pypdf
    
    # Extract text for language detection
    with open(pdf_path, 'rb') as f:
        reader = pypdf.PdfReader(f)
        text = ""
        for page in reader.pages[:3]:  # First 3 pages
            text += page.extract_text()
    
    # Detect language
    detected_lang = detect_language(text[:2000])
    
    # Call original extraction with detected language
    result = extract_from_pdf(pdf_path, filename)
    
    # Add detected language to result
    if isinstance(result, dict):
        result['detected_language'] = detected_lang
    
    return result
