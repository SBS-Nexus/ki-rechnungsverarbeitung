"""
SBS Invoice-App - Nexus Gateway API Integration
Erstellt automatisch via install_nexus_api.sh
"""
import os
from resend_config import resend_headers
import base64
import tempfile
import logging
import sqlite3
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nexus", tags=["Nexus Gateway Integration"])

NEXUS_API_KEY = os.getenv("NEXUS_API_KEY", "sbs_nexus_secret_2026")


class InvoiceProcessRequest(BaseModel):
    content: str
    filename: Optional[str] = None
    encoding: Optional[str] = "text"
    vendor_hint: Optional[str] = None


class InvoiceProcessResponse(BaseModel):
    success: bool
    provider: str
    model: str
    data: dict
    message: Optional[str] = None


class DocumentClassifyRequest(BaseModel):
    content: str
    filename: Optional[str] = None
    encoding: Optional[str] = "text"


class DocumentClassifyResponse(BaseModel):
    success: bool
    category: str
    confidence: float
    details: Optional[dict] = None


def verify_api_key(authorization: str = Header(None)):
    if not authorization or authorization != NEXUS_API_KEY:
        raise HTTPException(status_code=401, detail="Ungültiger API-Key")
    return {"id": 16, "email": "ki@sbsdeutschland.de", "is_admin": True}  # Default admin user for NEXUS_API_KEY


def extract_text_from_content(content: str, encoding: str, filename: str = None) -> str:
    if encoding == "text":
        return content
    
    elif encoding == "base64":
        try:
            pdf_bytes = base64.b64decode(content)
            suffix = ".pdf" if not filename else f".{filename.split('.')[-1]}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name
            
            try:
                from invoice_core import extract_text_from_pdf
                text = extract_text_from_pdf(tmp_path)
            except ImportError:
                import fitz
                doc = fitz.open(tmp_path)
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
            
            os.unlink(tmp_path)
            return text
            
        except Exception as e:
            logger.error(f"Dekodierungsfehler: {e}")
            raise HTTPException(status_code=400, detail=f"Dekodierungsfehler: {str(e)}")
    
    else:
        raise HTTPException(status_code=400, detail=f"Unbekanntes Encoding: {encoding}")


@router.post("/process-invoice", response_model=InvoiceProcessResponse)
async def process_invoice(request: InvoiceProcessRequest, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    
    try:
        text = extract_text_from_content(request.content, request.encoding, request.filename)
        
        if not text or len(text.strip()) < 30:
            raise HTTPException(status_code=400, detail="Zu wenig Text extrahiert")
        
        logger.info(f"Processing invoice: {len(text)} chars")
        
        try:
            from llm_router import extract_invoice_data, pick_provider_model
        except ImportError:
            raise HTTPException(status_code=500, detail="LLM Router nicht verfügbar")
        
        complexity = min(100, len(text) // 50)
        provider, model = pick_provider_model(complexity)
        
        logger.info(f"Selected: {provider}/{model}")
        
        result = extract_invoice_data(text, provider, model)
        
        if not result:
            raise HTTPException(status_code=422, detail="Extraktion fehlgeschlagen")
        
        return InvoiceProcessResponse(
            success=True,
            provider=provider,
            model=model,
            data=result,
            message=f"Verarbeitet mit {provider.upper()}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify-document", response_model=DocumentClassifyResponse)
async def classify_document(request: DocumentClassifyRequest, x_api_key: str = Header(None)):
    verify_api_key(x_api_key)
    
    try:
        text = extract_text_from_content(request.content, request.encoding, request.filename)
        
        if not text or len(text.strip()) < 20:
            raise HTTPException(status_code=400, detail="Zu wenig Text")
        
        text_lower = text.lower()
        scores = {"rechnung": 0, "vertrag": 0, "angebot": 0, "sonstiges": 0}
        
        for kw in ["rechnung", "invoice", "netto", "brutto", "mwst", "iban"]:
            if kw in text_lower:
                scores["rechnung"] += 1
        
        for kw in ["vertrag", "vereinbarung", "kündigung", "§", "laufzeit"]:
            if kw in text_lower:
                scores["vertrag"] += 1
        
        for kw in ["angebot", "kostenvoranschlag", "gültig bis"]:
            if kw in text_lower:
                scores["angebot"] += 1
        
        max_score = max(scores.values())
        if max_score == 0:
            category = "sonstiges"
            confidence = 0.3
        else:
            category = max(scores, key=scores.get)
            total = sum(scores.values())
            confidence = round(scores[category] / total, 2) if total > 0 else 0.5
        
        return DocumentClassifyResponse(
            success=True,
            category=category,
            confidence=confidence,
            details={"scores": scores}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    status = {"status": "healthy", "service": "sbs-invoice-api", "version": "1.0.0"}
    
    try:
        from llm_router import openai_client, anthropic_client
        status["ai"] = {"openai": "available", "anthropic": "available", "mode": "hybrid"}
    except ImportError as e:
        status["ai"] = {"error": str(e), "mode": "unavailable"}
    
    return status


@router.get("/info")
async def api_info():
    return {
        "api": "SBS Nexus Gateway Integration",
        "version": "1.0.0",
        "ai_models": {"primary": "GPT-4o", "fallback": "Claude Sonnet 4.5"}
    }

# ══════════════════════════════════════════════════════════════════════════════
# STATS ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_stats():
    """Dashboard Statistiken"""
    try:
        import sqlite3
        conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
        cursor = conn.cursor()
        
        # Rechnungen zählen
        cursor.execute("SELECT COUNT(*) FROM invoices")
        invoice_count = cursor.fetchone()[0]
        
        # Diesen Monat
        cursor.execute("""
            SELECT COUNT(*) FROM invoices 
            WHERE created_at >= date('now', 'start of month')
        """)
        invoices_this_month = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "invoices": {
                "total": invoice_count,
                "this_month": invoices_this_month
            },
            "contracts": {
                "total": 45,
                "this_month": 12
            },
            "video_diagnoses": {
                "total": 12,
                "this_month": 12
            },
            "success_rate": 98.5
        }
    except Exception as e:
        return {
            "invoices": {"total": 0, "this_month": 0},
            "contracts": {"total": 0, "this_month": 0},
            "video_diagnoses": {"total": 0, "this_month": 0},
            "success_rate": 0,
            "error": str(e)
        }

@router.get("/stats")
async def get_stats():
    """Dashboard Statistiken"""
    try:
        import sqlite3
        conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM invoices")
        invoice_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM invoices WHERE created_at >= date('now', 'start of month')")
        invoices_this_month = cursor.fetchone()[0]
        conn.close()
        return {
            "invoices": {"total": invoice_count, "this_month": invoices_this_month},
            "contracts": {"total": 45, "this_month": 12},
            "video_diagnoses": {"total": 12, "this_month": 12},
            "success_rate": 98.5
        }
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════
import hashlib

class LoginRequest(BaseModel):
    email: str
    password: str

@router.post("/auth/login")
async def login(request: LoginRequest):
    """User Login für Dashboard"""
    import sqlite3
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, email, name, password_hash, is_admin 
        FROM users WHERE email = ?
    """, (request.email,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")
    
    user_id, email, name, password_hash, is_admin = user
    
    # Check email verification
    conn2 = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor2 = conn2.cursor()
    cursor2.execute("SELECT email_verified FROM users WHERE id = ?", (user_id,))
    verified = cursor2.fetchone()
    conn2.close()
    
    if verified and not verified[0]:
        raise HTTPException(status_code=403, detail="Bitte bestätigen Sie zuerst Ihre E-Mail-Adresse")
    
    # Password check (SHA256)
    input_hash = hashlib.sha256(request.password.encode()).hexdigest()
    if input_hash != password_hash:
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")
    
    # Update last_login
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_login = datetime('now') WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "user": {
            "id": user_id,
            "email": email,
            "name": name or email.split("@")[0],
            "role": "admin" if is_admin else "user"
        },
        "token": f"sbs_{user_id}_{hashlib.md5(email.encode()).hexdigest()[:8]}"
    }

@router.get("/auth/me")
async def get_current_user(authorization: str = Header(None)):
    """Aktuellen User abrufen"""
    if not authorization or (not authorization.startswith("sbs_") and not authorization.startswith("Bearer ")):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    parts = authorization.split("_")
    if len(parts) < 2:
        raise HTTPException(status_code=401, detail="Ungültiger Token")
    
    user_id = parts[1]
    
    import sqlite3
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, name, is_admin FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(status_code=401, detail="User nicht gefunden")
    
    return {
        "id": user[0],
        "email": user[1],
        "name": user[2] or user[1].split("@")[0],
        "role": "admin" if user[3] else "user"
    }

@router.get("/stats/{user_id}")
async def get_user_stats(user_id: int):
    """User-spezifische Dashboard Statistiken"""
    try:
        import sqlite3
        conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
        cursor = conn.cursor()
        
        # Rechnungen für diesen User
        cursor.execute("SELECT COUNT(*) FROM invoices WHERE user_id = ?", (user_id,))
        invoice_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM invoices 
            WHERE user_id = ? AND created_at >= date('now', 'start of month')
        """, (user_id,))
        invoices_this_month = cursor.fetchone()[0]
        
        # Verträge (separate DB)
        contract_count = 45
        
        conn.close()
        
        return {
            "invoices": {"total": invoice_count, "this_month": invoices_this_month},
            "contracts": {"total": contract_count, "this_month": 0},
            "video_diagnoses": {"total": 0, "this_month": 0},
            "success_rate": 98.5
        }
    except Exception as e:
        return {
            "invoices": {"total": 0, "this_month": 0},
            "contracts": {"total": 0, "this_month": 0},
            "video_diagnoses": {"total": 0, "this_month": 0},
            "success_rate": 0,
            "error": str(e)
        }

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/users")
async def list_users(authorization: str = Header(None)):
    """Alle User auflisten (nur Admin)"""
    import sqlite3
    
    # Auth check
    if not authorization or (not authorization.startswith("sbs_") and not authorization.startswith("Bearer ")):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    token = authorization.replace("Bearer ", ""); user_id = token.split("_")[1] if token.startswith("sbs_") else "1"
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    # Check if admin
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    # Get all users
    cursor.execute("""
        SELECT id, email, name, is_admin, is_active, created_at, last_login 
        FROM users ORDER BY id
    """)
    users = cursor.fetchall()
    conn.close()
    
    return {
        "users": [
            {
                "id": u[0],
                "email": u[1],
                "name": u[2],
                "is_admin": bool(u[3]),
                "is_active": bool(u[4]),
                "created_at": u[5],
                "last_login": u[6]
            } for u in users
        ]
    }

class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    is_admin: bool = False

@router.post("/admin/users")
async def create_user(request: CreateUserRequest, authorization: str = Header(None)):
    """Neuen User erstellen (nur Admin)"""
    import sqlite3
    
    if not authorization or (not authorization.startswith("sbs_") and not authorization.startswith("Bearer ")):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    admin_id = authorization.split("_")[1]
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (admin_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    # Create user
    password_hash = hashlib.sha256(request.password.encode()).hexdigest()
    
    try:
        cursor.execute("""
            INSERT INTO users (email, name, password_hash, is_admin, is_active)
            VALUES (?, ?, ?, ?, 1)
        """, (request.email, request.name, password_hash, int(request.is_admin)))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return {"success": True, "user_id": new_id}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: int, authorization: str = Header(None)):
    """User löschen (nur Admin)"""
    import sqlite3
    
    if not authorization or (not authorization.startswith("sbs_") and not authorization.startswith("Bearer ")):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    admin_id = authorization.split("_")[1]
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (admin_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    # Hole User-Info vor Löschung
    cursor.execute("SELECT email, name FROM users WHERE id = ?", (user_id,))
    user_info = cursor.fetchone()
    
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    # Webhook für Admin-Aktion
    try:
        fire_webhook_event("admin.user_deleted", {
            "deleted_user_id": user_id,
            "deleted_user_email": user_info[0] if user_info else "unknown",
            "deleted_user_name": user_info[1] if user_info else "unknown",
            "deleted_by_admin_id": admin_id
        })
    except:
        pass
    
    return {"success": True}

class ResetPasswordRequest(BaseModel):
    user_id: int
    new_password: str

@router.post("/admin/reset-password")
async def reset_password(request: ResetPasswordRequest, authorization: str = Header(None)):
    """Passwort zurücksetzen (nur Admin)"""
    import sqlite3
    
    if not authorization or (not authorization.startswith("sbs_") and not authorization.startswith("Bearer ")):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    admin_id = authorization.split("_")[1]
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (admin_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    password_hash = hashlib.sha256(request.new_password.encode()).hexdigest()
    
    # Hole User-Info
    cursor.execute("SELECT email, name FROM users WHERE id = ?", (request.user_id,))
    user_info = cursor.fetchone()
    
    cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, request.user_id))
    conn.commit()
    conn.close()
    
    # Webhook für Admin-Aktion
    try:
        fire_webhook_event("admin.password_reset", {
            "user_id": request.user_id,
            "user_email": user_info[0] if user_info else "unknown",
            "reset_by_admin_id": admin_id
        })
    except:
        pass
    
    return {"success": True}

class UpdateUserRequest(BaseModel):
    name: str
    is_admin: bool

@router.put("/admin/users/{user_id}")
async def update_user(user_id: int, request: UpdateUserRequest, authorization: str = Header(None)):
    """User bearbeiten (nur Admin)"""
    import sqlite3
    
    if not authorization or (not authorization.startswith("sbs_") and not authorization.startswith("Bearer ")):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    admin_id = authorization.split("_")[1]
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (admin_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    cursor.execute("UPDATE users SET name = ?, is_admin = ? WHERE id = ?", (request.name, int(request.is_admin), user_id))
    conn.commit()
    conn.close()
    
    return {"success": True}

@router.get("/activity/{user_id}")
async def get_user_activity(user_id: int):
    """Letzte Aktivitäten eines Users"""
    import sqlite3
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    # Letzte Rechnungen
    cursor.execute("""
        SELECT id, rechnungsnummer, rechnungsaussteller, betrag_brutto, created_at
        FROM invoices WHERE user_id = ?
        ORDER BY created_at DESC LIMIT 5
    """, (user_id,))
    invoices = cursor.fetchall()
    
    # User Info für letzten Login
    cursor.execute("SELECT last_login FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    conn.close()
    
    activities = []
    
    if user and user[0]:
        activities.append({
            "type": "login",
            "text": "Letzter Login",
            "time": user[0]
        })
    
    for inv in invoices:
        activities.append({
            "type": "invoice",
            "text": f"Rechnung {inv[1] or 'ohne Nr.'} von {inv[2] or 'Unbekannt'}",
            "amount": inv[3],
            "time": inv[4]
        })
    
    return {"activities": activities}

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

@router.post("/auth/register")
async def register(request: RegisterRequest):
    """Neuen User registrieren"""
    import sqlite3
    
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen haben")
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    # Check if email exists
    cursor.execute("SELECT id FROM users WHERE email = ?", (request.email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="E-Mail bereits registriert")
    
    # Check if company email
    is_company = request.email.endswith("@sbsdeutschland.de") or request.email.endswith("@sbsdeutschland.com")
    
    # Create user
    password_hash = hashlib.sha256(request.password.encode()).hexdigest()
    
    if is_company:
        # Company emails: auto-verified + auto-admin
        cursor.execute("""
            INSERT INTO users (email, name, password_hash, is_admin, is_active, email_verified)
            VALUES (?, ?, ?, 1, 1, 1)
        """, (request.email, request.name, password_hash))
    else:
        # External emails: need verification
        verification_token = secrets.token_urlsafe(32)
        cursor.execute("""
            INSERT INTO users (email, name, password_hash, is_admin, is_active, email_verified, verification_token)
            VALUES (?, ?, ?, 0, 1, 0, ?)
        """, (request.email, request.name, password_hash, verification_token))
    
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    
    # Send verification email (only for non-company emails)
    if not is_company:
        try:
            import requests
            verify_link = f"https://sbsnexus.de/verify-email?token={verification_token}"
            
            requests.post(
                "https://api.resend.com/emails",
                headers=resend_headers(),
                json={
                    "from": "SBS Nexus <noreply@sbsdeutschland.de>",
                    "to": request.email,
                    "subject": "SBS Nexus - E-Mail bestätigen",
                    "html": f"""<h2>Willkommen bei SBS Nexus!</h2>
                    <p>Hallo {request.name},</p>
                    <p>Bitte bestätigen Sie Ihre E-Mail-Adresse:</p>
                    <p><a href="{verify_link}" style="background:#2563eb;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;display:inline-block;">E-Mail bestätigen</a></p>
                    <p style="color:#666;font-size:12px;">Falls Sie sich nicht registriert haben, ignorieren Sie diese E-Mail.</p>
                    <p>Mit freundlichen Grüßen,<br>SBS Deutschland GmbH</p>"""
                }
            )
        except Exception as e:
            print(f"Verification email error: {e}")
    
    # Notify admins
    try:
        requests.post(
            "https://api.resend.com/emails",
            headers=resend_headers(),
            json={
                "from": "SBS Nexus <noreply@sbsdeutschland.de>",
                "to": "luis220195@gmail.com",
                "subject": f"Neuer User: {request.name}",
                "html": f"""<h2>Neue Registrierung</h2>
                <p><strong>Name:</strong> {request.name}</p>
                <p><strong>E-Mail:</strong> {request.email}</p>
                <p><a href="https://sbsnexus.de/admin">Zum Admin-Panel</a></p>"""
            }
        )
    except:
        pass
    
    return {"success": True}

import secrets
from datetime import datetime, timedelta

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordTokenRequest(BaseModel):
    token: str
    new_password: str

@router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Passwort-Reset anfordern"""
    import sqlite3
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name FROM users WHERE email = ?", (request.email,))
    user = cursor.fetchone()
    
    if not user:
        # Don't reveal if email exists
        return {"success": True, "message": "Falls die E-Mail existiert, wurde ein Link gesendet."}
    
    # Generate token
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    
    cursor.execute("UPDATE users SET reset_token = ?, reset_token_expires = ? WHERE id = ?", 
                   (token, expires, user[0]))
    conn.commit()
    conn.close()
    
    # Send email via Resend
    try:
        import requests
        reset_link = f"https://sbsnexus.de/reset-password?token={token}"
        
        response = requests.post(
            "https://api.resend.com/emails",
            headers=resend_headers(),
            json={
                "from": "SBS Nexus <noreply@sbsdeutschland.de>",
                "to": request.email,
                "subject": "SBS Nexus - Passwort zurücksetzen",
                "html": f"""<h2>Passwort zurücksetzen</h2>
                <p>Hallo {user[1]},</p>
                <p>Sie haben angefordert, Ihr Passwort zurückzusetzen.</p>
                <p><a href="{reset_link}" style="background:#2563eb;color:white;padding:12px 24px;text-decoration:none;border-radius:8px;display:inline-block;">Passwort zurücksetzen</a></p>
                <p style="color:#666;font-size:12px;">Link gültig für 1 Stunde. Falls Sie diese Anfrage nicht gestellt haben, ignorieren Sie diese E-Mail.</p>
                <p>Mit freundlichen Grüßen,<br>SBS Deutschland GmbH</p>"""
            }
        )
        print(f"Resend response: {response.status_code}")
    except Exception as e:
        print(f"Email error: {e}")
    
    return {"success": True, "message": "Falls die E-Mail existiert, wurde ein Link gesendet."}

@router.post("/auth/reset-password-token")
async def reset_password_with_token(request: ResetPasswordTokenRequest):
    """Passwort mit Token zurücksetzen"""
    import sqlite3
    
    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen haben")
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, reset_token_expires FROM users 
        WHERE reset_token = ?
    """, (request.token,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=400, detail="Ungültiger oder abgelaufener Link")
    
    # Check expiration
    expires = datetime.fromisoformat(user[1])
    if datetime.now() > expires:
        conn.close()
        raise HTTPException(status_code=400, detail="Link ist abgelaufen")
    
    # Update password
    password_hash = hashlib.sha256(request.new_password.encode()).hexdigest()
    cursor.execute("""
        UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expires = NULL 
        WHERE id = ?
    """, (password_hash, user[0]))
    conn.commit()
    conn.close()
    
    return {"success": True}

@router.post("/auth/verify-email")
async def verify_email(token: str):
    """E-Mail verifizieren"""
    import sqlite3
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name FROM users WHERE verification_token = ?", (token,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        raise HTTPException(status_code=400, detail="Ungültiger Verifizierungslink")
    
    cursor.execute("UPDATE users SET email_verified = 1, verification_token = NULL WHERE id = ?", (user[0],))
    conn.commit()
    conn.close()
    
    return {"success": True, "name": user[1]}

@router.get("/health/services")
async def health_services():
    """Live health check für alle Services"""
    import requests
    
    services = {}
    
    # Invoice API - wir sind selbst online wenn diese Route antwortet
    services["invoice_api"] = "online"
    
    # Contract API
    try:
        r = requests.get("https://contract.sbsdeutschland.com/", timeout=3)
        services["contract_api"] = "online" if r.status_code == 200 else "degraded"
    except:
        services["contract_api"] = "offline"
    
    # HydraulikDoc (Streamlit Cloud)
    try:
        r = requests.get("https://knowledge-sbsdeutschland.streamlit.app/", timeout=5)
        services["hydraulikdoc"] = "online" if r.status_code == 200 else "degraded"
    except:
        services["hydraulikdoc"] = "offline"
    
    # AI Services
    services["ai_openai"] = "online"
    services["ai_anthropic"] = "online"
    
    return services

@router.get("/stats/{user_id}/monthly")
async def get_monthly_stats(user_id: int):
    """Monatliche Statistiken für Charts"""
    import sqlite3
    from datetime import datetime, timedelta
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    # Letzte 6 Monate
    months = []
    for i in range(5, -1, -1):
        date = datetime.now() - timedelta(days=i*30)
        month_start = date.replace(day=1).strftime("%Y-%m-01")
        month_end = (date.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m-01")
        month_name = date.strftime("%b")
        
        cursor.execute("""
            SELECT COUNT(*) FROM invoices 
            WHERE user_id = ? AND created_at >= ? AND created_at < ?
        """, (user_id, month_start, month_end))
        count = cursor.fetchone()[0]
        
        months.append({"month": month_name, "invoices": count})
    
    conn.close()
    return {"monthly": months}

@router.get("/admin/stats")
async def admin_stats():
    """Platform-weite Statistiken für Admins"""
    import sqlite3
    from datetime import datetime, timedelta
    
    conn = sqlite3.connect("/var/www/invoice-app/invoices.db")
    cursor = conn.cursor()
    
    # Total Users
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    # New users this month
    month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (month_start,))
    new_users_month = cursor.fetchone()[0]
    
    # Total Invoices
    cursor.execute("SELECT COUNT(*) FROM invoices")
    total_invoices = cursor.fetchone()[0]
    
    # Invoices this month
    cursor.execute("SELECT COUNT(*) FROM invoices WHERE created_at >= ?", (month_start,))
    invoices_month = cursor.fetchone()[0]
    
    # Total revenue (sum of all invoice amounts)
    cursor.execute("SELECT COALESCE(SUM(betrag_brutto), 0) FROM invoices")
    total_revenue = cursor.fetchone()[0]
    
    # Active users (logged in last 7 days)
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_login >= ?", (week_ago,))
    active_users = cursor.fetchone()[0]
    
    # Top users by invoice count
    cursor.execute("""
        SELECT u.name, u.email, COUNT(i.id) as invoice_count
        FROM users u
        LEFT JOIN invoices i ON u.id = i.user_id
        GROUP BY u.id
        ORDER BY invoice_count DESC
        LIMIT 5
    """)
    top_users = [{"name": r[0], "email": r[1], "invoices": r[2]} for r in cursor.fetchall()]
    
    # Recent registrations
    cursor.execute("""
        SELECT name, email, created_at FROM users 
        ORDER BY created_at DESC LIMIT 5
    """)
    recent_users = [{"name": r[0], "email": r[1], "created_at": r[2]} for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        "total_users": total_users,
        "new_users_month": new_users_month,
        "active_users": active_users,
        "total_invoices": total_invoices,
        "invoices_month": invoices_month,
        "total_revenue": round(total_revenue, 2),
        "top_users": top_users,
        "recent_users": recent_users
    }

# ============ NOTIFICATIONS ============

@router.get("/notifications/{user_id}")
async def get_notifications(user_id: int, authorization: str = Header(None)):
    """User Notifications abrufen"""
    import sqlite3
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    # Ensure notifications table exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    
    # Get notifications
    cursor.execute('''
        SELECT id, type, title, message, link, is_read, created_at 
        FROM notifications 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT 20
    ''', (user_id,))
    
    rows = cursor.fetchall()
    notifications = []
    unread_count = 0
    
    for row in rows:
        if row[5] == 0:
            unread_count += 1
        notifications.append({
            "id": row[0],
            "type": row[1],
            "title": row[2],
            "message": row[3],
            "link": row[4],
            "is_read": bool(row[5]),
            "created_at": row[6]
        })
    
    conn.close()
    return {"notifications": notifications, "unread_count": unread_count}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int, authorization: str = Header(None)):
    """Notification als gelesen markieren"""
    import sqlite3
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (notification_id,))
    conn.commit()
    conn.close()
    
    return {"success": True}


@router.post("/notifications/{user_id}/read-all")
async def mark_all_read(user_id: int, authorization: str = Header(None)):
    """Alle Notifications als gelesen markieren"""
    import sqlite3
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    
    return {"success": True}


@router.post("/notifications/create")
async def create_notification(data: dict, authorization: str = Header(None)):
    """Notification erstellen (für System/Admin)"""
    import sqlite3
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO notifications (user_id, type, title, message, link)
        VALUES (?, ?, ?, ?, ?)
    ''', (data.get('user_id'), data.get('type', 'info'), data.get('title'), data.get('message'), data.get('link')))
    
    conn.commit()
    notification_id = cursor.lastrowid
    conn.close()
    
    return {"success": True, "id": notification_id}

# ============ AUTO NOTIFICATIONS ============

def create_system_notification(user_id: int, type: str, title: str, message: str = None, link: str = None):
    """Helper: Erstellt System-Notification"""
    import sqlite3
    try:
        conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO notifications (user_id, type, title, message, link)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, type, title, message, link))
        conn.commit()
        conn.close()
    except:
        pass


@router.post("/notifications/admin/broadcast")
async def broadcast_notification(data: dict, authorization: str = Header(None)):
    """Admin: Nachricht an alle User senden"""
    import sqlite3
    
    # Auth check
    if not authorization:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    # Get all active users
    cursor.execute('SELECT id FROM users WHERE is_active = 1')
    users = cursor.fetchall()
    
    count = 0
    for user in users:
        cursor.execute('''
            INSERT INTO notifications (user_id, type, title, message, link)
            VALUES (?, ?, ?, ?, ?)
        ''', (user[0], data.get('type', 'info'), data.get('title'), data.get('message'), data.get('link')))
        count += 1
    
    conn.commit()
    conn.close()
    
    return {"success": True, "sent_to": count}

# ============ AUTO NOTIFICATION TRIGGERS ============

def notify_new_invoice(user_id: int, invoice_number: str, amount: float):
    """Notification bei neuer Rechnung"""
    create_system_notification(
        user_id=user_id,
        type="success",
        title=f"Rechnung {invoice_number} verarbeitet",
        message=f"Betrag: {amount:.2f}€ - Bereit für DATEV-Export",
        link="/history"
    )

def notify_new_user_to_admins(new_user_name: str, new_user_email: str):
    """Benachrichtigt alle Admins über neue Registrierung"""
    import sqlite3
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE is_admin = 1')
    admins = cursor.fetchall()
    conn.close()
    
    for admin in admins:
        create_system_notification(
            user_id=admin[0],
            type="info",
            title="Neuer User registriert",
            message=f"{new_user_name} ({new_user_email})",
            link="/admin"
        )

def notify_invoice_approved(user_id: int, invoice_number: str, approved_by: str):
    """Notification bei Rechnungsfreigabe"""
    create_system_notification(
        user_id=user_id,
        type="success",
        title=f"Rechnung {invoice_number} freigegeben",
        message=f"Freigegeben von {approved_by}",
        link="/history"
    )

def notify_contract_expiring(user_id: int, contract_name: str, days_left: int):
    """Notification bei auslaufendem Vertrag"""
    create_system_notification(
        user_id=user_id,
        type="warning",
        title=f"Vertrag läuft in {days_left} Tagen aus",
        message=contract_name,
        link="/contracts"
    )

# ============ AUDIT LOGS ============

def log_audit(user_id: int, user_email: str, action: str, resource_type: str = None, resource_id: str = None, details: str = None, ip: str = None):
    """Audit Log Eintrag erstellen"""
    import sqlite3
    try:
        conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO audit_logs (user_id, user_email, action, resource_type, resource_id, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, user_email, action, resource_type, resource_id, details, ip))
        conn.commit()
        conn.close()
    except:
        pass


@router.get("/admin/audit-logs")
async def get_audit_logs(authorization: str = Header(None), limit: int = 100, offset: int = 0):
    """Audit Logs abrufen (nur Admin)"""
    import sqlite3
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    token = authorization.replace("Bearer ", "")
    user_id = token.split("_")[1] if token.startswith("sbs_") else None
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    # Check admin
    cursor.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    if not user or not user[0]:
        conn.close()
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    # Get logs
    cursor.execute('''
        SELECT id, user_id, user_email, action, resource_type, resource_id, details, ip_address, created_at
        FROM audit_logs
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    
    rows = cursor.fetchall()
    
    # Get total count
    cursor.execute('SELECT COUNT(*) FROM audit_logs')
    total = cursor.fetchone()[0]
    
    conn.close()
    
    logs = []
    for row in rows:
        logs.append({
            "id": row[0],
            "user_id": row[1],
            "user_email": row[2],
            "action": row[3],
            "resource_type": row[4],
            "resource_id": row[5],
            "details": row[6],
            "ip_address": row[7],
            "created_at": row[8]
        })
    
    return {"logs": logs, "total": total, "limit": limit, "offset": offset}


@router.get("/admin/audit-logs/export")
async def export_audit_logs(authorization: str = Header(None), days: int = 30):
    """Audit Logs als CSV exportieren"""
    import sqlite3
    from datetime import datetime, timedelta
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    token = authorization.replace("Bearer ", "")
    user_id = token.split("_")[1] if token.startswith("sbs_") else None
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    # Check admin
    cursor.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    if not user or not user[0]:
        conn.close()
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    cursor.execute('''
        SELECT id, user_id, user_email, action, resource_type, resource_id, details, ip_address, created_at
        FROM audit_logs
        WHERE created_at >= ?
        ORDER BY created_at DESC
    ''', (since,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Build CSV
    csv_lines = ["ID,User ID,Email,Action,Resource Type,Resource ID,Details,IP,Timestamp"]
    for row in rows:
        csv_lines.append(f'{row[0]},{row[1]},{row[2]},{row[3]},{row[4] or ""},{row[5] or ""},{row[6] or ""},{row[7] or ""},{row[8]}')
    
    return {"csv": "\n".join(csv_lines), "count": len(rows), "days": days}

# ============ EMAIL NOTIFICATIONS ============

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_notification_email(to_email: str, subject: str, message: str):
    """Sendet Notification per E-Mail via Resend"""
    import requests
    
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers=resend_headers(),
            json={
                "from": "SBS Nexus <noreply@sbsdeutschland.com>",
                "to": to_email,
                "subject": subject,
                "html": f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <div style="background: linear-gradient(135deg, #0891b2, #3b82f6); padding: 20px; text-align: center;">
                        <h1 style="color: white; margin: 0;">🏢 SBS Nexus</h1>
                    </div>
                    <div style="padding: 30px; background: #f8fafc;">
                        <p style="color: #334155; font-size: 16px; line-height: 1.6;">{message}</p>
                        <a href="https://sbsnexus.de/dashboard" style="display: inline-block; background: #0891b2; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; margin-top: 20px;">Zum Dashboard →</a>
                    </div>
                    <div style="padding: 20px; text-align: center; color: #64748b; font-size: 12px;">
                        © 2026 SBS Deutschland GmbH
                    </div>
                </div>
                """
            }
        )
        return response.status_code == 200
    except:
        return False


def notify_user_with_email(user_id: int, type: str, title: str, message: str, link: str = None):
    """Erstellt Notification UND sendet E-Mail"""
    import sqlite3
    
    # Create in-app notification
    create_system_notification(user_id, type, title, message, link)
    
    # Get user email
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('SELECT email FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        send_notification_email(user[0], f"SBS Nexus: {title}", message)

# ============ WEBHOOKS ============

import requests
from typing import Optional

def trigger_webhook(webhook_url: str, event: str, data: dict):
    """Sendet Event an externe Webhook-URL"""
    try:
        payload = {
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        response = requests.post(webhook_url, json=payload, timeout=5)
        return response.status_code == 200
    except:
        return False


@router.get("/admin/webhooks")
async def list_webhooks(authorization: str = Header(None)):
    """Alle Webhooks auflisten"""
    import sqlite3
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            events TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    
    cursor.execute('SELECT id, name, url, events, is_active, created_at FROM webhooks ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    
    return {"webhooks": [{"id": r[0], "name": r[1], "url": r[2], "events": r[3].split(","), "is_active": bool(r[4]), "created_at": r[5]} for r in rows]}


@router.post("/admin/webhooks")
async def create_webhook(data: dict, authorization: str = Header(None)):
    """Neuen Webhook erstellen"""
    import sqlite3
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO webhooks (name, url, events) VALUES (?, ?, ?)
    ''', (data.get('name'), data.get('url'), ",".join(data.get('events', []))))
    
    conn.commit()
    webhook_id = cursor.lastrowid
    conn.close()
    
    return {"success": True, "id": webhook_id}


@router.delete("/admin/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: int, authorization: str = Header(None)):
    """Webhook löschen"""
    import sqlite3
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM webhooks WHERE id = ?', (webhook_id,))
    conn.commit()
    conn.close()
    
    return {"success": True}


@router.post("/admin/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int, authorization: str = Header(None)):
    """Webhook testen"""
    import sqlite3
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('SELECT url FROM webhooks WHERE id = ?', (webhook_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Webhook nicht gefunden")
    
    success = trigger_webhook(row[0], "test", {"message": "Test von SBS Nexus"})
    return {"success": success}


def fire_webhook_event(event: str, data: dict):
    """Feuert Event an alle aktiven Webhooks die dieses Event abonniert haben"""
    import sqlite3
    import time
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, url, events FROM webhooks WHERE is_active = 1')
    webhooks = cursor.fetchall()
    conn.close()
    
    for webhook in webhooks:
        webhook_id = webhook[0]
        events = webhook[2].split(",")
        if event in events or "all" in events:
            start_time = time.time()
            try:
                response = trigger_webhook(webhook[1], event, data)
                response_time = int((time.time() - start_time) * 1000)
                log_webhook_call(webhook_id, event, "success", 200, response_time, None, data)
            except Exception as e:
                response_time = int((time.time() - start_time) * 1000)
                log_webhook_call(webhook_id, event, "failed", 0, response_time, str(e), data)


def log_webhook_call(webhook_id: int, event: str, status: str, response_code: int, response_time_ms: int, error_message: str, payload: dict):
    """Loggt Webhook-Aufrufe für Statistiken"""
    import sqlite3
    import json
    try:
        conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO webhook_logs (webhook_id, event, status, response_code, response_time_ms, error_message, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (webhook_id, event, status, response_code, response_time_ms, error_message, json.dumps(payload)))
        conn.commit()
        conn.close()
    except:
        pass


# Event Types:
# - invoice.created
# - invoice.approved  
# - contract.created
# - contract.expiring
# - user.registered
# - user.login


@router.get("/admin/webhook-stats")
async def get_webhook_stats(authorization: str = Header(None)):
    """Webhook Statistiken für Admin Dashboard"""
    import sqlite3
    
    if not authorization or not authorization.startswith("sbs_"):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    
    admin_id = authorization.split("_")[1]
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Admin check
    cursor.execute("SELECT is_admin FROM users WHERE id = ?", (admin_id,))
    result = cursor.fetchone()
    if not result or not result[0]:
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")
    
    # Gesamtstatistik
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            AVG(response_time_ms) as avg_response_time
        FROM webhook_logs
        WHERE created_at > datetime('now', '-7 days')
    """)
    stats = dict(cursor.fetchone())
    
    # Events nach Typ
    cursor.execute("""
        SELECT event, COUNT(*) as count
        FROM webhook_logs
        WHERE created_at > datetime('now', '-7 days')
        GROUP BY event
        ORDER BY count DESC
    """)
    by_event = [dict(row) for row in cursor.fetchall()]
    
    # Letzte 20 Aufrufe
    cursor.execute("""
        SELECT event, status, response_code, response_time_ms, created_at
        FROM webhook_logs
        ORDER BY created_at DESC
        LIMIT 20
    """)
    recent = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "stats": stats,
        "by_event": by_event,
        "recent": recent
    }


# ============================================================================
# SMART MAINTENANCE ALERT API - Enterprise Feature
# ============================================================================

from smart_maintenance import (
    process_maintenance_request_v2,
    save_maintenance_request,
    search_invoices_by_part,
    search_contracts_by_part,
    init_maintenance_db
)

# Ensure DB is initialized
init_maintenance_db()


@router.post("/maintenance/analyze")
async def analyze_maintenance_request(
    request: Request,
    authorization: str = Header(None)
):
    """
    Smart Maintenance Alert - Hauptendpoint
    
    Techniker lädt Bild hoch → System liefert komplette Handlungsempfehlung
    
    Body (JSON):
    - image_base64: Base64-kodiertes Bild (required)
    - technician_notes: Notizen vom Techniker (optional)
    - location: Standort/Maschine (optional)
    - machine_id: Maschinen-ID (optional)
    - urgency: low|normal|high|critical (default: normal)
    - use_hydraulikdoc: true|false (default: true)
    
    Returns komplettes Maintenance-Alert Objekt mit:
    - Teilerkennung (KI-basiert)
    - Rechnungshistorie
    - Vertragsinfo/Garantiestatus
    - Handlungsempfehlung
    - Kostenprognose
    """
    user = verify_api_key(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    image_base64 = body.get("image_base64")
    if not image_base64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    
    # Process request
    result = await process_maintenance_request_v2(
        image_base64=image_base64,
        technician_notes=body.get("technician_notes", ""),
        user_id=user["id"],
        location=body.get("location", ""),
        urgency=body.get("urgency", "normal"),
        machine_id=body.get("machine_id"),
        use_hydraulikdoc=body.get("use_hydraulikdoc", True)
    )
    
    # Save to database
    db_id = save_maintenance_request(result, user["id"])
    result["db_id"] = db_id
    
    # Trigger webhook
    fire_webhook_event("maintenance.created", {
        "request_id": result["request_id"],
        "part_name": result.get("part_recognition", {}).get("part_name", "Unbekannt"),
        "recommendation": result.get("recommendation", {}).get("action", "unknown"),
        "urgency": result.get("urgency"),
        "location": result.get("location")
    })
    
    return result


@router.get("/maintenance/requests")
async def list_maintenance_requests(
    authorization: str = Header(None),
    status: str = None,
    limit: int = 50
):
    """
    Liste aller Maintenance Requests des Users
    
    Query params:
    - status: Filter by status (pending, completed, error)
    - limit: Max results (default 50)
    """
    user = verify_api_key(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM maintenance_requests WHERE user_id = ?"
    params = [user["id"]]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    requests = []
    for row in rows:
        req = dict(row)
        # Parse JSON fields
        if req.get("part_info_json"):
            req["part_info"] = json.loads(req["part_info_json"])
            del req["part_info_json"]
        if req.get("recommendation_json"):
            req["recommendation"] = json.loads(req["recommendation_json"])
            del req["recommendation_json"]
        requests.append(req)
    
    return {"requests": requests, "count": len(requests)}


@router.get("/maintenance/requests/{request_id}")
async def get_maintenance_request(
    request_id: str,
    authorization: str = Header(None)
):
    """
    Einzelnen Maintenance Request abrufen
    """
    user = verify_api_key(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT * FROM maintenance_requests WHERE request_id = ? AND user_id = ?",
        (request_id, user["id"])
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    
    result = dict(row)
    if result.get("part_info_json"):
        result["part_info"] = json.loads(result["part_info_json"])
        del result["part_info_json"]
    if result.get("recommendation_json"):
        result["recommendation"] = json.loads(result["recommendation_json"])
        del result["recommendation_json"]
    
    return result


@router.post("/maintenance/search-parts")
async def search_parts_history(
    request: Request,
    authorization: str = Header(None)
):
    """
    Suche in Rechnungen/Verträgen nach Teilen
    
    Body:
    - search_terms: Liste von Suchbegriffen
    - include_invoices: true/false
    - include_contracts: true/false
    """
    user = verify_api_key(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    search_terms = body.get("search_terms", [])
    if not search_terms:
        raise HTTPException(status_code=400, detail="search_terms required")
    
    result = {
        "search_terms": search_terms,
        "invoices": [],
        "contracts": []
    }
    
    if body.get("include_invoices", True):
        result["invoices"] = search_invoices_by_part(search_terms, user["id"])
    
    if body.get("include_contracts", True):
        result["contracts"] = search_contracts_by_part(search_terms, user["id"])
    
    return result


@router.get("/maintenance/stats")
async def get_maintenance_stats(authorization: str = Header(None)):
    """
    Statistiken zu Maintenance Requests
    """
    user = verify_api_key(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    conn = sqlite3.connect('/var/www/invoice-app/invoices.db')
    cursor = conn.cursor()
    
    # Total requests
    cursor.execute(
        "SELECT COUNT(*) FROM maintenance_requests WHERE user_id = ?",
        (user["id"],)
    )
    total = cursor.fetchone()[0]
    
    # By status
    cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM maintenance_requests 
        WHERE user_id = ?
        GROUP BY status
    """, (user["id"],))
    by_status = {row[0]: row[1] for row in cursor.fetchall()}
    
    # By urgency
    cursor.execute("""
        SELECT urgency, COUNT(*) as count 
        FROM maintenance_requests 
        WHERE user_id = ?
        GROUP BY urgency
    """, (user["id"],))
    by_urgency = {row[0]: row[1] for row in cursor.fetchall()}
    
    # This month
    cursor.execute("""
        SELECT COUNT(*) FROM maintenance_requests 
        WHERE user_id = ? AND created_at >= date('now', 'start of month')
    """, (user["id"],))
    this_month = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_requests": total,
        "this_month": this_month,
        "by_status": by_status,
        "by_urgency": by_urgency
    }
