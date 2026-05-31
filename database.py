#!/usr/bin/env python3
from cache import cached, CACHE_TTLS, invalidate_cache
"""
SQLite Database für Job-Persistenz
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("/var/www/invoice-app/invoices.db").resolve()

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize database tables"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Jobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            created_at TEXT,
            completed_at TEXT,
            status TEXT DEFAULT 'uploaded',
            total_files INTEGER DEFAULT 0,
            successful INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            total_amount REAL DEFAULT 0,
            total_netto REAL DEFAULT 0,
            total_mwst REAL DEFAULT 0,
            average_amount REAL DEFAULT 0,
            exported_files TEXT,
            upload_path TEXT,
            failed_list TEXT
        )
    ''')
    
    # Results table (individual invoices)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            rechnungsnummer TEXT,
            datum TEXT,
            faelligkeitsdatum TEXT,
            zahlungsziel_tage INTEGER,
            rechnungsaussteller TEXT,
            rechnungsaussteller_adresse TEXT,
            rechnungsempfaenger TEXT,
            rechnungsempfaenger_adresse TEXT,
            kundennummer TEXT,
            betrag_brutto REAL,
            betrag_netto REAL,
            mwst_betrag REAL,
            mwst_satz REAL,
            waehrung TEXT,
            iban TEXT,
            bic TEXT,
            steuernummer TEXT,
            ust_idnr TEXT,
            zahlungsbedingungen TEXT,
            artikel TEXT,
            verwendungszweck TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id)
        )
    ''')
    
    conn.commit()

    # Webhook für neue Rechnungen
    try:
        from api_nexus import fire_webhook_event
        for invoice in results:
            fire_webhook_event("invoice.created", {
                "invoice_number": invoice.get("rechnungsnummer", ""),
                "supplier": invoice.get("rechnungsaussteller", ""),
                "amount": invoice.get("betrag_brutto", 0),
                "date": invoice.get("datum", ""),
                "job_id": job_id
            })
    except:
        pass

    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    logger.info("Database initialized")

def save_job(job_id: str, job_data: Dict, user_id: int = None):
    """Save or update a job"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Prepare data
    exported_files = json.dumps(job_data.get('exported_files', {}))
    failed_list = json.dumps(job_data.get('failed', []))
    
    cursor.execute('''
        INSERT OR REPLACE INTO jobs (
            job_id, created_at, completed_at, status, total_files,
            successful, failed_count, total_amount, total_netto, total_mwst,
            average_amount, exported_files, upload_path, failed_list, user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        job_id,
        job_data.get('created_at', datetime.now().isoformat()),
        job_data.get('completed_at'),
        job_data.get('status', 'uploaded'),
        job_data.get('total', 0),
        job_data.get('successful', 0),
        len(job_data.get('failed', [])),
        job_data.get('total_amount', 0),
        job_data.get('stats', {}).get('total_netto', 0) if job_data.get('stats') else 0,
        job_data.get('stats', {}).get('total_mwst', 0) if job_data.get('stats') else 0,
        job_data.get('stats', {}).get('average_brutto', 0) if job_data.get('stats') else 0,
        exported_files,
        job_data.get('path', ''),
        failed_list,
        user_id
    ))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()


def save_invoices(job_id: str, results: List[Dict]):
    """Save invoice results for a job (inkl. E-Rechnungs-Metadaten)"""
    from duplicate_detection import (
        generate_invoice_hash,
        check_duplicate_by_hash,
        save_duplicate_detection,
    )
    import json
    import logging

    logger = logging.getLogger(__name__)

    # benutzt jetzt DB_PATH => invoices.db
    conn = get_connection()
    cursor = conn.cursor()

    # Bestehende Rechnungen dieses Jobs löschen (Re-Processing)
    cursor.execute("DELETE FROM invoices WHERE job_id = ?", (job_id,))

    for invoice in results:
        # 1) Hash für Duplikaterkennung
        content_hash = generate_invoice_hash(invoice)

        # 2) E-Rechnungs-Felder aus dem (in app.py) angereicherten Dict
        source_format = invoice.get("source_format", "pdf")
        einvoice_raw_xml = (
            invoice.get("einvoice_raw_xml")
            or invoice.get("raw_xml")
            or invoice.get("xml")
            or ""
        )
        einvoice_profile = invoice.get("einvoice_profile", "")

        raw_valid = invoice.get("einvoice_valid", False)
        if isinstance(raw_valid, bool):
            einvoice_valid = 1 if raw_valid else 0
        else:
            try:
                einvoice_valid = 1 if int(raw_valid) != 0 else 0
            except Exception:
                einvoice_valid = 0

        einvoice_validation_message = (
            invoice.get("einvoice_validation_message", "") or ""
        )

        cursor.execute(
            """
            INSERT INTO invoices (
                job_id, rechnungsnummer, datum, faelligkeitsdatum, zahlungsziel_tage,
                rechnungsaussteller, rechnungsaussteller_adresse, rechnungsempfaenger,
                rechnungsempfaenger_adresse, kundennummer, betrag_brutto, betrag_netto,
                mwst_betrag, mwst_satz, waehrung, iban, bic, steuernummer, ust_idnr,
                zahlungsbedingungen, artikel, verwendungszweck, content_hash,
                source_format, einvoice_raw_xml, einvoice_profile,
                einvoice_valid, einvoice_validation_message, confidence
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                job_id,
                invoice.get("rechnungsnummer", ""),
                invoice.get("datum", ""),
                invoice.get("faelligkeitsdatum", ""),
                invoice.get("zahlungsziel_tage", 0),
                invoice.get("rechnungsaussteller", ""),
                invoice.get("rechnungsaussteller_adresse", ""),
                invoice.get("rechnungsempfänger", invoice.get("rechnungsempfaenger", "")),
                invoice.get(
                    "rechnungsempfänger_adresse",
                    invoice.get("rechnungsempfaenger_adresse", ""),
                ),
                invoice.get("kundennummer", ""),
                invoice.get("betrag_brutto", 0),
                invoice.get("betrag_netto", 0),
                invoice.get("mwst_betrag", 0),
                invoice.get("mwst_satz", 0),
                invoice.get("waehrung", "EUR"),
                invoice.get("iban", ""),
                invoice.get("bic", ""),
                invoice.get("steuernummer", ""),
                invoice.get("ust_idnr", ""),
                invoice.get("zahlungsbedingungen", ""),
                json.dumps(invoice.get("artikel", [])),
                invoice.get("verwendungszweck", ""),
                content_hash,
                source_format,
                einvoice_raw_xml,
                einvoice_profile,
                einvoice_valid,
                einvoice_validation_message,
                invoice.get("confidence", 0.0),
            ),
        )

        invoice_id = cursor.lastrowid

        # 3) Duplikat-Check (Hash)
        duplicate = check_duplicate_by_hash(invoice, conn=conn)
        if duplicate and duplicate.get("id") != invoice_id:
            logger.warning(
                f"⚠️ Duplicate detected for invoice {invoice_id}: "
                f"matches invoice {duplicate['id']}"
            )
            save_duplicate_detection(
                invoice_id, duplicate["id"], method="hash", confidence=1.0, conn=conn
            )

    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()


def get_invoices_by_job(job_id: str) -> List[Dict]:
    """Get all invoices for a job with their IDs"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invoices WHERE job_id = ?", (job_id,))
    invoices = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return invoices
def get_job(job_id: str) -> Optional[Dict]:
    """Get a job by ID (inkl. Rechnungen & Basis-Statistiken)"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    job: Dict = dict(row)
    job['exported_files'] = json.loads(job.get('exported_files') or '{}')
    job['failed'] = json.loads(job.get('failed_list') or '[]')

    # Alle Rechnungen zu diesem Job
    cursor.execute("SELECT * FROM invoices WHERE job_id = ?", (job_id,))
    invoices = [dict(r) for r in cursor.fetchall()]
    job['results'] = invoices

    # Fallback: wenn total_files / successful leer oder 0 sind, aus Rechnungen ableiten
    if not job.get('total_files'):
        job['total_files'] = len(invoices)
    if not job.get('successful'):
        job['successful'] = len(invoices)

    conn.close()
    return job
def get_all_jobs(limit: int = 50, offset: int = 0, user_id: int = None) -> List[Dict]:
    """Get all jobs for a user, newest first"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute('''
            SELECT * FROM jobs 
            WHERE user_id = ?
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (user_id, limit, offset))
    else:
        cursor.execute('''
            SELECT * FROM jobs 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (limit, offset))
    
    jobs = []
    for row in cursor.fetchall():
        job = dict(row)
        job['exported_files'] = json.loads(job['exported_files'] or '{}')
        job['failed'] = json.loads(job['failed_list'] or '[]')
        jobs.append(job)
    
    conn.close()
    return jobs

@cached("statistics", ttl=300)
def get_statistics(user_id: int = None) -> Dict:
    """Get overall statistics - filtered by user_id"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build user filter
    user_where = "AND user_id = ?" if user_id else ""
    user_params = (user_id,) if user_id else ()
    
    # Total jobs
    cursor.execute(f'SELECT COUNT(*) FROM jobs WHERE status = "completed" {user_where}', user_params)
    total_jobs = cursor.fetchone()[0]
    
    # Total invoices (via jobs JOIN)
    if user_id:
        cursor.execute('''
            SELECT COUNT(*) FROM invoices i 
            INNER JOIN jobs j ON i.job_id = j.job_id 
            WHERE j.user_id = ?
        ''', (user_id,))
    else:
        cursor.execute('SELECT COUNT(*) FROM invoices')
    total_invoices = cursor.fetchone()[0]
    
    # Total amount
    cursor.execute(f'SELECT SUM(total_amount) FROM jobs WHERE status = "completed" {user_where}', user_params)
    total_amount = cursor.fetchone()[0] or 0
    
    # Success rate
    cursor.execute(f'SELECT SUM(successful), SUM(total_files) FROM jobs WHERE status = "completed" {user_where}', user_params)
    row = cursor.fetchone()
    successful = row[0] or 0
    total_files = row[1] or 0
    success_rate = (successful / total_files * 100) if total_files > 0 else 0
    
    # Average per invoice
    avg_per_invoice = (total_amount / total_invoices) if total_invoices > 0 else 0
    
    # Jobs per day (last 30 days)
    if user_id:
        cursor.execute('''
            SELECT DATE(created_at) as date, COUNT(*) as count, SUM(total_amount) as amount
            FROM jobs 
            WHERE status = "completed" AND user_id = ?
            AND created_at >= DATE('now', '-30 days')
            GROUP BY DATE(created_at)
            ORDER BY date
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT DATE(created_at) as date, COUNT(*) as count, SUM(total_amount) as amount
            FROM jobs 
            WHERE status = "completed" 
            AND created_at >= DATE('now', '-30 days')
            GROUP BY DATE(created_at)
            ORDER BY date
        ''')
    daily_data = [dict(r) for r in cursor.fetchall()]
    
    # Top Rechnungsaussteller (via jobs JOIN)
    if user_id:
        cursor.execute('''
            SELECT i.rechnungsaussteller, COUNT(*) as count, SUM(i.betrag_brutto) as total
            FROM invoices i
            INNER JOIN jobs j ON i.job_id = j.job_id
            WHERE i.rechnungsaussteller != '' AND j.user_id = ?
            GROUP BY i.rechnungsaussteller
            ORDER BY count DESC
            LIMIT 5
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT rechnungsaussteller, COUNT(*) as count, SUM(betrag_brutto) as total
            FROM invoices
            WHERE rechnungsaussteller != ''
            GROUP BY rechnungsaussteller
            ORDER BY count DESC
            LIMIT 5
        ''')
    top_aussteller = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        'total_jobs': total_jobs,
        'total_invoices': total_invoices,
        'total_amount': round(total_amount, 2),
        'success_rate': round(success_rate, 1),
        'avg_per_invoice': round(avg_per_invoice, 2),
        'daily_data': daily_data,
        'top_aussteller': top_aussteller
    }

# Initialize on import
init_database()

def get_analytics_data(user_id: int = None):
    """Get comprehensive analytics data - filtered by user_id"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build user filter - JOIN with jobs to filter by user
    if user_id:
        user_join = "INNER JOIN jobs j ON i.job_id = j.job_id"
        user_where = "AND j.user_id = ?"
        user_params = (user_id,)
    else:
        user_join = ""
        user_where = ""
        user_params = ()
    
    # Basic stats
    cursor.execute(f'SELECT COUNT(*) FROM invoices i {user_join} WHERE 1=1 {user_where}', user_params)
    total_invoices = cursor.fetchone()[0]
    
    cursor.execute(f'SELECT SUM(i.betrag_brutto), SUM(i.betrag_netto), SUM(i.mwst_betrag) FROM invoices i {user_join} WHERE 1=1 {user_where}', user_params)
    row = cursor.fetchone()
    total_brutto = row[0] or 0
    total_netto = row[1] or 0
    total_mwst = row[2] or 0
    
    # Unique suppliers
    cursor.execute(f'SELECT COUNT(DISTINCT i.rechnungsaussteller) FROM invoices i {user_join} WHERE i.rechnungsaussteller != "" {user_where}', user_params)
    unique_suppliers = cursor.fetchone()[0]
    
    # Average per invoice
    avg_per_invoice = (total_brutto / total_invoices) if total_invoices > 0 else 0
    
    # Monthly data
    cursor.execute(f'''
        SELECT strftime('%Y-%m', i.datum) as month, SUM(i.betrag_brutto) as total
        FROM invoices i {user_join}
        WHERE i.datum != '' AND i.datum IS NOT NULL {user_where}
        GROUP BY month
        ORDER BY month
        LIMIT 12
    ''', user_params)
    monthly_data = cursor.fetchall()
    monthly_labels = [r[0] for r in monthly_data] if monthly_data else []
    monthly_values = [r[1] or 0 for r in monthly_data] if monthly_data else []
    
    # Top suppliers
    cursor.execute(f'''
        SELECT i.rechnungsaussteller as name, COUNT(*) as count, SUM(i.betrag_brutto) as total
        FROM invoices i {user_join}
        WHERE i.rechnungsaussteller != '' AND i.rechnungsaussteller IS NOT NULL {user_where}
        GROUP BY i.rechnungsaussteller
        ORDER BY total DESC
        LIMIT 10
    ''', user_params)
    top_suppliers = [dict(r) for r in cursor.fetchall()]
    
    # Weekday distribution
    cursor.execute(f'''
        SELECT strftime('%w', i.datum) as weekday, COUNT(*) as count
        FROM invoices i {user_join}
        WHERE i.datum != '' AND i.datum IS NOT NULL {user_where}
        GROUP BY weekday
    ''', user_params)
    weekday_raw = {int(r[0]): r[1] for r in cursor.fetchall()}
    weekday_data = [weekday_raw.get((i + 1) % 7, 0) for i in range(7)]
    
    conn.close()
    
    return {
        'stats': {
            'total_invoices': total_invoices,
            'total_amount': round(total_brutto, 2),
            'total_netto': round(total_netto, 2),
            'total_mwst': round(total_mwst, 2),
            'avg_per_invoice': round(avg_per_invoice, 2),
            'unique_suppliers': unique_suppliers
        },
        'monthly_labels': monthly_labels,
        'monthly_values': monthly_values,
        'top_suppliers': top_suppliers,
        'weekday_data': weekday_data
    }

def init_feedback_table():
    """Initialize feedback/corrections table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            supplier TEXT,
            field_name TEXT,
            original_value TEXT,
            corrected_value TEXT,
            invoice_id INTEGER,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    # Supplier patterns table - learned patterns per supplier
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS supplier_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT UNIQUE,
            patterns TEXT,
            confidence REAL DEFAULT 0,
            invoice_count INTEGER DEFAULT 0,
            last_updated TEXT
        )
    ''')
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

# Initialize feedback tables
init_feedback_table()

def save_correction(invoice_id: int, supplier: str, field_name: str, original_value: str, corrected_value: str):
    """Save a user correction for learning"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO corrections (supplier, field_name, original_value, corrected_value, invoice_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (supplier, field_name, original_value, corrected_value, invoice_id))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    # Update supplier patterns
    update_supplier_patterns(supplier)

def update_supplier_patterns(supplier: str):
    """Update learned patterns for a supplier based on corrections"""
    import json
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get all corrections for this supplier
    cursor.execute('''
        SELECT field_name, corrected_value, COUNT(*) as count
        FROM corrections
        WHERE supplier = ?
        GROUP BY field_name, corrected_value
        ORDER BY count DESC
    ''', (supplier,))
    
    corrections = cursor.fetchall()
    
    # Build patterns
    patterns = {}
    for field, value, count in corrections:
        if field not in patterns:
            patterns[field] = []
        patterns[field].append({'value': value, 'count': count})
    
    # Count total invoices for this supplier
    cursor.execute('SELECT COUNT(*) FROM invoices WHERE rechnungsaussteller = ?', (supplier,))
    invoice_count = cursor.fetchone()[0]
    
    # Calculate confidence (more corrections = higher confidence)
    total_corrections = sum(c[2] for c in corrections)
    confidence = min(total_corrections / 10, 1.0)  # Max confidence at 10 corrections
    
    # Save patterns
    cursor.execute('''
        INSERT OR REPLACE INTO supplier_patterns (supplier, patterns, confidence, invoice_count, last_updated)
        VALUES (?, ?, ?, ?, ?)
    ''', (supplier, json.dumps(patterns), confidence, invoice_count, datetime.now().isoformat()))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def get_supplier_patterns(supplier: str) -> dict:
    """Get learned patterns for a supplier"""
    import json
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT patterns, confidence FROM supplier_patterns WHERE supplier = ?', (supplier,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return {
            'patterns': json.loads(row[0]),
            'confidence': row[1]
        }
    return {'patterns': {}, 'confidence': 0}

def update_invoice(invoice_id: int, updates: dict):
    """Update invoice with corrected values"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build UPDATE query dynamically
    set_clauses = []
    values = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = ?")
        values.append(value)
    
    values.append(invoice_id)
    
    query = f"UPDATE invoices SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, values)
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def get_invoice_by_id(invoice_id: int) -> dict:
    """Get single invoice by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return dict(row)
    return None

def init_feedback_table():
    """Initialize feedback/corrections table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            supplier TEXT,
            field_name TEXT,
            original_value TEXT,
            corrected_value TEXT,
            invoice_id INTEGER,
            FOREIGN KEY (invoice_id) REFERENCES invoices(id)
        )
    ''')
    
    # Supplier patterns table - learned patterns per supplier
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS supplier_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT UNIQUE,
            patterns TEXT,
            confidence REAL DEFAULT 0,
            invoice_count INTEGER DEFAULT 0,
            last_updated TEXT
        )
    ''')
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

# Initialize feedback tables
init_feedback_table()

def save_correction(invoice_id: int, supplier: str, field_name: str, original_value: str, corrected_value: str):
    """Save a user correction for learning"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO corrections (supplier, field_name, original_value, corrected_value, invoice_id)
        VALUES (?, ?, ?, ?, ?)
    ''', (supplier, field_name, original_value, corrected_value, invoice_id))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    # Update supplier patterns
    update_supplier_patterns(supplier)

def update_supplier_patterns(supplier: str):
    """Update learned patterns for a supplier based on corrections"""
    import json
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get all corrections for this supplier
    cursor.execute('''
        SELECT field_name, corrected_value, COUNT(*) as count
        FROM corrections
        WHERE supplier = ?
        GROUP BY field_name, corrected_value
        ORDER BY count DESC
    ''', (supplier,))
    
    corrections = cursor.fetchall()
    
    # Build patterns
    patterns = {}
    for field, value, count in corrections:
        if field not in patterns:
            patterns[field] = []
        patterns[field].append({'value': value, 'count': count})
    
    # Count total invoices for this supplier
    cursor.execute('SELECT COUNT(*) FROM invoices WHERE rechnungsaussteller = ?', (supplier,))
    invoice_count = cursor.fetchone()[0]
    
    # Calculate confidence (more corrections = higher confidence)
    total_corrections = sum(c[2] for c in corrections)
    confidence = min(total_corrections / 10, 1.0)  # Max confidence at 10 corrections
    
    # Save patterns
    cursor.execute('''
        INSERT OR REPLACE INTO supplier_patterns (supplier, patterns, confidence, invoice_count, last_updated)
        VALUES (?, ?, ?, ?, ?)
    ''', (supplier, json.dumps(patterns), confidence, invoice_count, datetime.now().isoformat()))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def get_supplier_patterns(supplier: str) -> dict:
    """Get learned patterns for a supplier"""
    import json
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT patterns, confidence FROM supplier_patterns WHERE supplier = ?', (supplier,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return {
            'patterns': json.loads(row[0]),
            'confidence': row[1]
        }
    return {'patterns': {}, 'confidence': 0}

def update_invoice(invoice_id: int, updates: dict):
    """Update invoice with corrected values"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Build UPDATE query dynamically
    set_clauses = []
    values = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = ?")
        values.append(value)
    
    values.append(invoice_id)
    
    query = f"UPDATE invoices SET {', '.join(set_clauses)} WHERE id = ?"
    cursor.execute(query, values)
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def get_invoice_by_id(invoice_id: int) -> dict:
    """Get single invoice by ID"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM invoices WHERE id = ?', (invoice_id,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return dict(row)
    return None

def init_email_inbox_table():
    """Initialize email inbox configuration table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_inbox_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enabled INTEGER DEFAULT 0,
            email_address TEXT,
            imap_server TEXT,
            imap_port INTEGER DEFAULT 993,
            username TEXT,
            password TEXT,
            folder TEXT DEFAULT 'INBOX',
            filter_from TEXT,
            filter_subject TEXT,
            auto_process INTEGER DEFAULT 1,
            last_check TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_processed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            from_address TEXT,
            subject TEXT,
            received_at TEXT,
            processed_at TEXT,
            job_id TEXT,
            status TEXT,
            attachments_count INTEGER
        )
    ''')
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

init_email_inbox_table()

def get_email_config():
    """Get email inbox configuration"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM email_inbox_config ORDER BY id DESC LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_email_config(config: dict):
    """Save email inbox configuration"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Delete existing config
    cursor.execute('DELETE FROM email_inbox_config')
    
    cursor.execute('''
        INSERT INTO email_inbox_config 
        (enabled, email_address, imap_server, imap_port, username, password, folder, filter_from, filter_subject, auto_process)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        config.get('enabled', 0),
        config.get('email_address', ''),
        config.get('imap_server', ''),
        config.get('imap_port', 993),
        config.get('username', ''),
        config.get('password', ''),
        config.get('folder', 'INBOX'),
        config.get('filter_from', ''),
        config.get('filter_subject', ''),
        config.get('auto_process', 1)
    ))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def save_processed_email(message_id: str, from_addr: str, subject: str, job_id: str, attachments: int):
    """Save record of processed email"""
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO email_processed 
        (message_id, from_address, subject, received_at, processed_at, job_id, status, attachments_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (message_id, from_addr, subject, datetime.now().isoformat(), datetime.now().isoformat(), job_id, 'processed', attachments))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def is_email_processed(message_id: str) -> bool:
    """Check if email was already processed"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM email_processed WHERE message_id = ?', (message_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def init_users_table():
    """Initialize users table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            company TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Add user_id to jobs table if not exists
    cursor.execute("PRAGMA table_info(jobs)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'user_id' not in columns:
        cursor.execute('ALTER TABLE jobs ADD COLUMN user_id INTEGER')
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

init_users_table()

def create_user(email: str, password: str, name: str = '', company: str = '') -> int:
    """Create new user, returns user_id"""
    from password_utils import hash_password

    password_hash = hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO users (email, password_hash, name, company)
        VALUES (?, ?, ?, ?)
    ''', (email, password_hash, name, company))
    
    user_id = cursor.lastrowid
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    return user_id

def verify_user(email: str, password: str) -> dict:
    """Verify user credentials, returns user dict or None"""
    from datetime import datetime
    from password_utils import verify_password, needs_rehash, hash_password

    conn = get_connection()
    cursor = conn.cursor()

    # Hash NICHT mehr in der SQL-WHERE-Klausel vergleichen – stattdessen den
    # gespeicherten Hash laden und mit verify_password() prüfen. Das erlaubt
    # bcrypt/PBKDF2 (gesalzen) und unterstützt Legacy-SHA-256 weiterhin.
    cursor.execute('''
        SELECT id, email, name, company, is_active, password_hash
        FROM users
        WHERE email = ?
    ''', (email,))

    row = cursor.fetchone()

    if row and row[4] and verify_password(password, row[5]):  # is_active + Passwort korrekt
        # Transparentes Upgrade veralteter Hashes auf das starke Verfahren
        if needs_rehash(row[5]):
            try:
                cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                              (hash_password(password), row[0]))
            except Exception:
                pass
        # Update last login
        cursor.execute('UPDATE users SET last_login = ? WHERE id = ?',
                      (datetime.now().isoformat(), row[0]))
        conn.commit()
        conn.close()
        return {'id': row[0], 'email': row[1], 'name': row[2], 'company': row[3]}

    conn.close()
    return None

def get_user_by_id(user_id: int) -> dict:
    """Get user by ID inkl. Admin-Status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, email, name, company, is_admin, totp_enabled FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return {
            'id': row[0], 
            'email': row[1], 
            'name': row[2], 
            'company': row[3],
            'is_admin': bool(row[4]) if row[4] is not None else False,
            'totp_enabled': bool(row[5]) if row[5] is not None else False
        }
    return None

def email_exists(email: str) -> bool:
    """Check if email already exists"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def init_users_table():
    """Initialize users table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT,
            company TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Add user_id to jobs table if not exists
    cursor.execute("PRAGMA table_info(jobs)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'user_id' not in columns:
        cursor.execute('ALTER TABLE jobs ADD COLUMN user_id INTEGER')
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

init_users_table()

def create_user(email: str, password: str, name: str = '', company: str = '') -> int:
    """Create new user, returns user_id"""
    from password_utils import hash_password

    password_hash = hash_password(password)

    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO users (email, password_hash, name, company)
        VALUES (?, ?, ?, ?)
    ''', (email, password_hash, name, company))
    
    user_id = cursor.lastrowid
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    return user_id

def verify_user(email: str, password: str) -> dict:
    """Verify user credentials, returns user dict or None"""
    from datetime import datetime
    from password_utils import verify_password, needs_rehash, hash_password

    conn = get_connection()
    cursor = conn.cursor()

    # Hash NICHT mehr in der SQL-WHERE-Klausel vergleichen – stattdessen den
    # gespeicherten Hash laden und mit verify_password() prüfen. Das erlaubt
    # bcrypt/PBKDF2 (gesalzen) und unterstützt Legacy-SHA-256 weiterhin.
    cursor.execute('''
        SELECT id, email, name, company, is_active, password_hash
        FROM users
        WHERE email = ?
    ''', (email,))

    row = cursor.fetchone()

    if row and row[4] and verify_password(password, row[5]):  # is_active + Passwort korrekt
        # Transparentes Upgrade veralteter Hashes auf das starke Verfahren
        if needs_rehash(row[5]):
            try:
                cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                              (hash_password(password), row[0]))
            except Exception:
                pass
        # Update last login
        cursor.execute('UPDATE users SET last_login = ? WHERE id = ?',
                      (datetime.now().isoformat(), row[0]))
        conn.commit()
        conn.close()
        return {'id': row[0], 'email': row[1], 'name': row[2], 'company': row[3]}

    conn.close()
    return None

def get_user_by_id(user_id: int) -> dict:
    """Get user by ID inkl. Admin-Status"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, email, name, company, is_admin, totp_enabled FROM users WHERE id = ?', (user_id,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return {
            'id': row[0], 
            'email': row[1], 
            'name': row[2], 
            'company': row[3],
            'is_admin': bool(row[4]) if row[4] is not None else False,
            'totp_enabled': bool(row[5]) if row[5] is not None else False
        }
    return None

def email_exists(email: str) -> bool:
    """Check if email already exists"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def init_subscriptions_table():
    """Initialize subscriptions table"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            status TEXT DEFAULT 'active',
            invoices_limit INTEGER,
            invoices_used INTEGER DEFAULT 0,
            current_period_start TEXT,
            current_period_end TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

init_subscriptions_table()

def get_user_subscription(user_id: int) -> dict:
    """Get user's active subscription"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM subscriptions 
        WHERE user_id = ? AND status = 'active' 
        ORDER BY created_at DESC LIMIT 1
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_subscription(user_id: int, plan: str, stripe_customer_id: str, stripe_subscription_id: str):
    """Create new subscription"""
    limits = {'starter': 100, 'professional': 600, 'enterprise': 999999}
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO subscriptions 
        (user_id, plan, stripe_customer_id, stripe_subscription_id, invoices_limit, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    ''', (user_id, plan, stripe_customer_id, stripe_subscription_id, limits.get(plan, 100)))
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def check_invoice_limit(user_id: int) -> dict:
    """Check if user can process more invoices"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if user is admin (unlimited access)
    cursor.execute('SELECT is_admin FROM users WHERE id = ?', (user_id,))
    user_row = cursor.fetchone()
    if user_row and user_row[0]:
        conn.close()
        return {
            'allowed': True,
            'is_admin': True,
            'plan': 'admin',
            'limit': 999999,
            'used': 0,
            'remaining': 999999,
            'message': 'Admin-Account - Unbegrenzter Zugang'
        }
    
    # Get active subscription
    cursor.execute('''
        SELECT plan, invoices_limit, invoices_used 
        FROM subscriptions 
        WHERE user_id = ? AND status = 'active' 
        ORDER BY created_at DESC LIMIT 1
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {
            'allowed': False,
            'reason': 'no_subscription',
            'plan': None,
            'limit': 0,
            'used': 0,
            'message': 'Kein aktives Abonnement. Bitte wählen Sie einen Plan.'
        }
    
    plan, limit, used = row[0], row[1], row[2]
    remaining = limit - used
    
    if remaining <= 0:
        return {
            'allowed': False,
            'reason': 'limit_reached',
            'message': f'Monatliches Limit erreicht ({used}/{limit}). Bitte upgraden Sie Ihren Plan.',
            'plan': plan,
            'limit': limit,
            'used': used
        }
    
    return {
        'allowed': True,
        'plan': plan,
        'limit': limit,
        'used': used,
        'remaining': remaining
    }

def increment_invoice_usage(user_id: int, count: int = 1):
    """Increment the invoice usage counter"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE subscriptions 
        SET invoices_used = invoices_used + ?
        WHERE user_id = ? AND status = 'active'
    ''', (count, user_id))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def reset_monthly_usage():
    """Reset all usage counters (call monthly via cron)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE subscriptions SET invoices_used = 0 WHERE status = "active"')
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

# Add user_id column to existing jobs table if not exists
def add_user_id_to_jobs():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('ALTER TABLE jobs ADD COLUMN user_id INTEGER')
        conn.commit()
        print("Added user_id column to jobs table")
    except:
        pass  # Column already exists
    conn.close()

add_user_id_to_jobs()

def get_analytics_insights(user_id: int = None) -> list:
    """Generate actionable insights from analytics data - filtered by user_id"""
    conn = get_connection()
    cursor = conn.cursor()
    insights = []
    
    # Build user filter
    if user_id:
        user_join = "INNER JOIN jobs j ON i.job_id = j.job_id"
        user_where = "AND j.user_id = ?"
        user_params = (user_id,)
    else:
        user_join = ""
        user_where = ""
        user_params = ()
    
    # Insight 1: Top Suppliers
    cursor.execute(f'''
        SELECT i.rechnungsaussteller, COUNT(*) as count, SUM(i.betrag_brutto) as total
        FROM invoices i {user_join}
        WHERE i.rechnungsaussteller != '' {user_where}
        GROUP BY i.rechnungsaussteller
        ORDER BY total DESC
        LIMIT 3
    ''', user_params)
    top_suppliers = cursor.fetchall()
    if top_suppliers:
        total_all = sum(r[2] or 0 for r in top_suppliers)
        cursor.execute(f'SELECT SUM(i.betrag_brutto) FROM invoices i {user_join} WHERE 1=1 {user_where}', user_params)
        grand_total = cursor.fetchone()[0] or 1
        percentage = (total_all / grand_total * 100) if grand_total > 0 else 0
        insights.append({
            'icon': '💡',
            'type': 'info',
            'title': 'Top-Lieferanten Konzentration',
            'message': f'Deine Top-3 Lieferanten machen {percentage:.1f}% der Gesamtausgaben aus'
        })
    
    # Insight 2: Monthly Trend
    cursor.execute(f'''
        SELECT strftime('%Y-%m', i.datum) as month, SUM(i.betrag_brutto) as total
        FROM invoices i {user_join}
        WHERE i.datum != '' AND i.datum IS NOT NULL {user_where}
        GROUP BY month
        ORDER BY month DESC
        LIMIT 2
    ''', user_params)
    months = cursor.fetchall()
    if len(months) == 2:
        current, previous = months[0][1], months[1][1]
        if current and previous:
            change = ((current - previous) / previous * 100)
            icon = '📈' if change > 0 else '📉'
            direction = 'höher' if change > 0 else 'niedriger'
            insights.append({
                'icon': icon,
                'type': 'warning' if change > 20 else 'info',
                'title': 'Monatlicher Trend',
                'message': f'Ausgaben sind {abs(change):.1f}% {direction} als letzter Monat'
            })
    
    # Insight 3: Processing Stats
    cursor.execute(f'SELECT COUNT(*), AVG(i.betrag_brutto) FROM invoices i {user_join} WHERE 1=1 {user_where}', user_params)
    stats = cursor.fetchone()
    if stats[0]:
        insights.append({
            'icon': '✨',
            'type': 'success',
            'title': 'Verarbeitungs-Performance',
            'message': f'{stats[0]} Rechnungen verarbeitet · Ø {stats[1]:.2f}€ pro Rechnung'
        })
    
    conn.close()
    return insights

# ==================== CATEGORIES ====================

def get_all_categories(user_id: int = None):
    """Get all categories (user-specific or global)"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    if user_id:
        cursor.execute('SELECT * FROM categories WHERE user_id IS NULL OR user_id = ?', (user_id,))
    else:
        cursor.execute('SELECT * FROM categories WHERE user_id IS NULL')
    categories = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return categories

def create_category(name: str, description: str = None, account_number: str = None, 
                   color: str = '#3B82F6', icon: str = '📁', user_id: int = None):
    """Create new category"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO categories (name, description, account_number, color, icon, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (name, description, account_number, color, icon, user_id))
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    category_id = cursor.lastrowid
    conn.close()
    return category_id

def assign_category_to_invoice(invoice_id: int, category_id: int, confidence: float = 1.0, assigned_by: str = 'user'):
    """Assign category to invoice"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO invoice_categories (invoice_id, category_id, confidence, assigned_by)
        VALUES (?, ?, ?, ?)
    ''', (invoice_id, category_id, confidence, assigned_by))
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def get_invoice_categories(invoice_id: int):
    """Get categories for an invoice"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT c.*, ic.confidence, ic.assigned_by
        FROM categories c
        JOIN invoice_categories ic ON c.id = ic.category_id
        WHERE ic.invoice_id = ?
    ''', (invoice_id,))
    categories = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return categories

def save_category_learning(supplier_name: str, category_id: int, invoice_text: str, user_id: int = None):
    """Save learning data for future predictions"""
    conn = get_connection()
    cursor = conn.cursor()
    snippet = invoice_text[:500] if invoice_text else ""
    
    # Check if exists
    cursor.execute('''
        SELECT id, times_confirmed FROM category_learning 
        WHERE supplier_name = ? AND category_id = ? AND user_id = ?
    ''', (supplier_name, category_id, user_id))
    
    existing = cursor.fetchone()
    if existing:
        # Update existing
        cursor.execute('''
            UPDATE category_learning 
            SET times_confirmed = times_confirmed + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (existing['id'],))
    else:
        # Insert new
        cursor.execute('''
            INSERT INTO category_learning (supplier_name, category_id, invoice_text_snippet, user_id)
            VALUES (?, ?, ?, ?)
        ''', (supplier_name, category_id, snippet, user_id))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()

def get_learned_category(supplier_name: str, user_id: int = None):
    """Get learned category for a supplier"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT category_id, times_confirmed 
        FROM category_learning 
        WHERE supplier_name = ? AND (user_id IS NULL OR user_id = ?)
        ORDER BY times_confirmed DESC, updated_at DESC
        LIMIT 1
    ''', (supplier_name, user_id))
    result = cursor.fetchone()
    conn.close()
    return dict(result) if result else None


def get_duplicates_for_job(job_id: str):
    """Get all duplicate detections for a job"""
    import sqlite3
    
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            dd.id as detection_id,
            dd.confidence,
            dd.detection_method,
            i1.id as invoice_id,
            i1.rechnungsnummer as invoice_rechnungsnummer,
            i1.rechnungsaussteller as invoice_aussteller,
            i1.betrag_brutto as invoice_betrag,
            i2.id as original_id,
            i2.rechnungsnummer as original_rechnungsnummer,
            i2.datum as original_datum,
            i2.betrag_brutto as original_betrag
        FROM duplicate_detections dd
        JOIN invoices i1 ON dd.invoice_id = i1.id
        JOIN invoices i2 ON dd.duplicate_of_id = i2.id
        WHERE i1.job_id = ? AND dd.status = 'pending'
        ORDER BY dd.confidence DESC
    ''', (job_id,))
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return results

# --- Job-bezogene Rechnungsabfragen (einheitliche Implementierung) ---

import sqlite3
from pathlib import Path as _Path

def _get_invoice_conn():
    """
    Öffnet direkt die invoices.db im Projektverzeichnis.
    Nutzt sqlite3.Row, damit wir Dicts zurückgeben können.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def get_invoices_by_job(job_id: str) -> List[Dict]:
    """Get all invoices for a job with their IDs"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM invoices WHERE job_id = ?", (job_id,))
    invoices = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return invoices
def get_invoices_for_job(job_id: str):
    """Alias für get_invoices_by_job (Kompatibilität)."""
    return get_invoices_by_job(job_id)

def get_plausibility_warnings_for_job(job_id: str):
    """Get all plausibility warnings for a job"""
    import json
    
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            pc.id,
            pc.check_type,
            pc.severity,
            pc.confidence,
            pc.details,
            pc.status,
            i.rechnungsnummer as invoice_rechnungsnummer,
            i.rechnungsaussteller as invoice_aussteller
        FROM plausibility_checks pc
        JOIN invoices i ON pc.invoice_id = i.id
        WHERE i.job_id = ?
        AND pc.status = 'pending'
        ORDER BY 
            CASE pc.severity
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                ELSE 3
            END,
            pc.confidence DESC
    ''', (job_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    warnings = []
    for row in rows:
        warning = dict(row)
        # Parse JSON details
        try:
            warning['details_json'] = json.loads(warning['details'])
        except:
            warning['details_json'] = {}
        warnings.append(warning)
    
    return warnings


# =====================================================
# PASSWORD RESET & EMAIL VERIFICATION
# =====================================================

def create_password_reset_token(email: str) -> Optional[str]:
    """Create password reset token for user"""
    import secrets
    from datetime import datetime, timedelta
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get user
    cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        return None
    
    # Generate token
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
    
    # Save token
    cursor.execute('''
        INSERT INTO password_reset_tokens (user_id, token, expires_at)
        VALUES (?, ?, ?)
    ''', (user['id'], token, expires_at))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    return token


def verify_reset_token(token: str) -> Optional[int]:
    """Verify password reset token and return user_id"""
    from datetime import datetime
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, expires_at, used 
        FROM password_reset_tokens 
        WHERE token = ?
    ''', (token,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return None
    
    if result['used']:
        return None
    
    # Check expiration
    expires_at = datetime.fromisoformat(result['expires_at'])
    if datetime.now() > expires_at:
        return None
    
    return result['user_id']


def reset_password(token: str, new_password: str) -> bool:
    """Reset user password with token"""
    from password_utils import hash_password

    user_id = verify_reset_token(token)
    if not user_id:
        return False

    conn = get_connection()
    cursor = conn.cursor()

    # Hash new password (bcrypt bzw. PBKDF2 – zentral via password_utils)
    password_hash = hash_password(new_password)

    # Update password
    cursor.execute('''
        UPDATE users
        SET password_hash = ?
        WHERE id = ?
    ''', (password_hash, user_id))
    
    # Mark token as used
    cursor.execute('''
        UPDATE password_reset_tokens 
        SET used = 1 
        WHERE token = ?
    ''', (token,))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    return True


def create_email_verification_token(user_id: int) -> str:
    """Create email verification token"""
    import secrets
    
    token = secrets.token_urlsafe(32)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE users 
        SET verification_token = ?
        WHERE id = ?
    ''', (token, user_id))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    return token


def verify_email(token: str) -> bool:
    """Verify user email with token"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE users 
        SET email_verified = 1, verification_token = NULL
        WHERE verification_token = ?
    ''', (token,))
    
    success = cursor.rowcount > 0
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    
    return success

# ===========================================
# ### OVERRIDE: password reset helpers (saubere Version)
# ===========================================
from typing import Optional

def create_password_reset_token(email: str) -> Optional[str]:
    """Create password reset token for user (24h gültig)."""
    import secrets
    from datetime import datetime, timedelta

    conn = get_connection()
    conn.row_factory = sqlite3.Row if hasattr(conn, "row_factory") else conn.row_factory
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    user_id = row["id"]

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now() + timedelta(hours=24)).isoformat()

    # used-Spalte, falls vorhanden, direkt mit 0 setzen
    try:
        cursor.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at, used) VALUES (?, ?, ?, 0)",
            (user_id, token, expires_at),
        )
    except Exception:
        # Fallback, falls alte Tabelle ohne 'used' existiert
        cursor.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
            (user_id, token, expires_at),
        )

    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    return token


def verify_reset_token(token: str) -> Optional[int]:
    """Verify password reset token and return user_id or None."""
    from datetime import datetime

    conn = get_connection()
    conn.row_factory = sqlite3.Row if hasattr(conn, "row_factory") else conn.row_factory
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, expires_at, used FROM password_reset_tokens WHERE token = ?",
        (token,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    user_id = row["user_id"]
    expires_at = row["expires_at"]
    used = row["used"]

    if used:
        return None

    try:
        expires_dt = datetime.fromisoformat(expires_at)
    except Exception:
        return None

    if datetime.now() > expires_dt:
        return None

    return user_id


def reset_password(token: str, new_password: str) -> bool:
    """Reset user password with token, using zentrales sicheres Hashing."""
    from password_utils import hash_password

    user_id = verify_reset_token(token)
    if not user_id:
        return False

    conn = get_connection()
    cursor = conn.cursor()

    password_hash = hash_password(new_password)
    cursor.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )

    # Token als benutzt markieren, falls Spalte existiert
    try:
        cursor.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE token = ?",
            (token,),
        )
    except Exception:
        pass

    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    return True



# =============================================================================
# REPOSITORY FUNKTIONEN (neu hinzugefügt)
# =============================================================================

def find_potential_duplicates(
    invoice_number: str,
    supplier_name: str,
    gross_amount: float,
    exclude_job_id: str = None
) -> List[Dict]:
    """Findet potenzielle Duplikate basierend auf Rechnungsnummer, Lieferant und Betrag"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
        SELECT * FROM invoices 
        WHERE (invoice_number = ? OR (supplier_name = ? AND gross_amount = ?))
    """
    params = [invoice_number, supplier_name, gross_amount]
    
    if exclude_job_id:
        query += " AND job_id != ?"
        params.append(exclude_job_id)
    
    cursor.execute(query, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_invoice_stats(user_id: int = None) -> Dict:
    """Holt aggregierte Statistiken für Rechnungen"""
    conn = get_connection()
    cursor = conn.cursor()
    
    base_query = """
        SELECT 
            COUNT(*) as total_invoices,
            SUM(CASE WHEN i.status = 'ok' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN is_duplicate = 1 THEN 1 ELSE 0 END) as duplicates,
            SUM(gross_amount) as total_gross,
            SUM(net_amount) as total_net,
            SUM(vat_amount) as total_vat,
            COUNT(DISTINCT supplier_name) as unique_suppliers
        FROM invoices i
    """
    
    if user_id:
        base_query += " JOIN jobs j ON i.job_id = j.job_id WHERE j.user_id = ?"
        cursor.execute(base_query, (user_id,))
    else:
        cursor.execute(base_query)
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "total_invoices": row[0] or 0,
            "successful": row[1] or 0,
            "duplicates": row[2] or 0,
            "total_gross": row[3] or 0.0,
            "total_net": row[4] or 0.0,
            "total_vat": row[5] or 0.0,
            "unique_suppliers": row[6] or 0
        }
    return {}


def get_jobs_by_status(status: str, user_id: int = None, limit: int = 50) -> List[Dict]:
    """Holt Jobs nach Status"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
            (status, user_id, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        )
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_invoices_by_supplier(supplier_name: str, user_id: int = None, limit: int = 100) -> List[Dict]:
    """Holt alle Rechnungen eines Lieferanten"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute("""
            SELECT i.* FROM invoices i
            JOIN jobs j ON i.job_id = j.job_id
            WHERE i.supplier_name LIKE ? AND j.user_id = ?
            ORDER BY i.invoice_date DESC
            LIMIT ?
        """, (f"%{supplier_name}%", user_id, limit))
    else:
        cursor.execute("""
            SELECT * FROM invoices 
            WHERE supplier_name LIKE ?
            ORDER BY invoice_date DESC
            LIMIT ?
        """, (f"%{supplier_name}%", limit))
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


@cached("monthly_summary", ttl=600)
def get_monthly_summary(user_id: int = None, months: int = 12) -> List[Dict]:
    """Holt monatliche Zusammenfassung der Rechnungen"""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            strftime('%Y-%m', invoice_date) as month,
            COUNT(*) as invoice_count,
            SUM(gross_amount) as total_gross,
            SUM(net_amount) as total_net,
            SUM(vat_amount) as total_vat
        FROM invoices i
    """
    
    if user_id:
        query += " JOIN jobs j ON i.job_id = j.job_id WHERE j.user_id = ?"
        query += " GROUP BY month ORDER BY month DESC LIMIT ?"
        cursor.execute(query, (user_id, months))
    else:
        query += " GROUP BY month ORDER BY month DESC LIMIT ?"
        cursor.execute(query, (months,))
    
    results = []
    for row in cursor.fetchall():
        results.append({
            "month": row[0],
            "invoice_count": row[1],
            "total_gross": row[2] or 0.0,
            "total_net": row[3] or 0.0,
            "total_vat": row[4] or 0.0
        })
    
    conn.close()
    return results


def delete_job(job_id: str, user_id: int = None) -> bool:
    """Löscht einen Job und alle zugehörigen Rechnungen (mit User-Check)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Prüfen ob Job existiert und User berechtigt ist
    if user_id:
        cursor.execute("SELECT job_id FROM jobs WHERE job_id = ? AND user_id = ?", (job_id, user_id))
    else:
        cursor.execute("SELECT job_id FROM jobs WHERE job_id = ?", (job_id,))
    
    if not cursor.fetchone():
        conn.close()
        return False
    
    # Rechnungen löschen
    cursor.execute("DELETE FROM invoices WHERE job_id = ?", (job_id,))
    
    # Job löschen
    cursor.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    return True


def update_job_status(job_id: str, status: str, **extra_fields) -> bool:
    """Aktualisiert den Job-Status und optionale weitere Felder"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Basis-Update
    updates = ["status = ?"]
    params = [status]
    
    # Optionale Felder
    allowed_fields = ['processed_files', 'successful_files', 'failed_files', 
                      'total_net', 'total_vat', 'total_gross', 'completed_at']
    
    for field, value in extra_fields.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            params.append(value)
    
    params.append(job_id)
    
    query = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"
    cursor.execute(query, params)
    
    success = cursor.rowcount > 0
    conn.commit()
    # Cache invalidieren nach neuen Invoices
    invalidate_cache("statistics")
    invalidate_cache("monthly_summary")
    conn.close()
    return success


def get_confidence_distribution(user_id: int = None) -> dict:
    """Holt KI-Konfidenz-Verteilung für Analytics."""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            SUM(CASE WHEN confidence >= 0.8 THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN confidence >= 0.5 AND confidence < 0.8 THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN confidence < 0.5 OR confidence IS NULL THEN 1 ELSE 0 END) as low
        FROM invoices
    """
    
    if user_id:
        query += " JOIN jobs ON invoices.job_id = jobs.job_id WHERE jobs.user_id = ?"
        cursor.execute(query, (user_id,))
    else:
        cursor.execute(query)
    
    row = cursor.fetchone()
    conn.close()
    
    return {
        'high': row[0] or 0,
        'medium': row[1] or 0,
        'low': row[2] or 0,
        'distribution': [row[0] or 0, row[1] or 0, row[2] or 0]
    }


def get_method_distribution(user_id: int = None) -> dict:
    """Holt Verarbeitungs-Methoden-Verteilung für Analytics."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Prüfe ob source_format vorhanden ist
    query = """
        SELECT 
            SUM(CASE WHEN source_format = 'vision' THEN 1 ELSE 0 END) as vision,
            SUM(CASE WHEN source_format != 'vision' OR source_format IS NULL THEN 1 ELSE 0 END) as text
        FROM invoices
    """
    
    if user_id:
        query += " JOIN jobs ON invoices.job_id = jobs.job_id WHERE jobs.user_id = ?"
        cursor.execute(query, (user_id,))
    else:
        cursor.execute(query)
    
    row = cursor.fetchone()
    conn.close()
    
    text_count = row[1] or 0
    vision_count = row[0] or 0
    
    return {
        'text': text_count,
        'vision': vision_count,
        'distribution': [text_count, vision_count]
    }


def log_export(user_id: int, job_id: str, export_type: str, filename: str = None, 
               file_size: int = 0, invoice_count: int = 0, total_amount: float = 0):
    """Protokolliert einen Export."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO export_history (user_id, job_id, export_type, filename, file_size, invoice_count, total_amount)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, job_id, export_type, filename, file_size, invoice_count, total_amount))
    conn.commit()
    conn.close()


def get_export_history(user_id: int = None, limit: int = 100):
    """Holt Export-Historie."""
    conn = get_connection()
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute("SELECT * FROM export_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    else:
        cursor.execute("SELECT * FROM export_history ORDER BY created_at DESC LIMIT ?", (limit,))
    
    exports = cursor.fetchall()
    conn.close()
    return exports


def get_export_stats(user_id: int = None):
    """Holt Export-Statistiken."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if user_id:
        cursor.execute("SELECT COUNT(*) FROM export_history WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM export_history WHERE user_id = ? AND created_at > datetime('now', '-7 days')", (user_id,))
        this_week = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(invoice_count), 0) FROM export_history WHERE user_id = ?", (user_id,))
        total_invoices = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM export_history WHERE user_id = ?", (user_id,))
        total_amount = cursor.fetchone()[0]
    else:
        cursor.execute("SELECT COUNT(*) FROM export_history")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM export_history WHERE created_at > datetime('now', '-7 days')")
        this_week = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(invoice_count), 0) FROM export_history")
        total_invoices = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM export_history")
        total_amount = cursor.fetchone()[0]
    
    conn.close()
    return {"total": total, "this_week": this_week, "total_invoices": total_invoices, "total_amount": total_amount}

