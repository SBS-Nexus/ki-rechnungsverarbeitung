#!/usr/bin/env python3
"""
SBS Nexus — Steuerberater Outreach Sender
==========================================
Sendet alle 7 Prio-A E-Mails via Resend API.

Usage:
  python3 sbs_outreach_sender.py --preview            # E-Mails anzeigen ohne zu senden
  python3 sbs_outreach_sender.py --send-test          # Test an eigene Adresse
  python3 sbs_outreach_sender.py --send               # ALLE 7 E-Mails senden
  python3 sbs_outreach_sender.py --send --batch 1     # Nur Batch 1 (Heimatmarkt)
  python3 sbs_outreach_sender.py --send --batch 2     # Nur Batch 2 (Frankfurt)
  python3 sbs_outreach_sender.py --send --batch 3     # Nur Batch 3 (Stuttgart+Koeln)
"""

import requests
from resend_config import resend_headers
import json
import time
import sys
import os
import argparse
from datetime import datetime

# ============================================================
# KONFIGURATION
# ============================================================
FROM_EMAIL = "luis@sbsdeutschland.de"
FROM_NAME = "Luis Schenk | SBS Deutschland"
REPLY_TO = "ki@sbsdeutschland.de"
TEST_EMAIL = "luis@schenk.com"

CALENDLY = "https://calendly.com/ki-sbsdeutschland"
LINKEDIN = "https://www.linkedin.com/company/sbs-deutschland-gmbh-co-kg/"
TELEFON = "06201 24469"
WEBSITE = "https://www.sbsnexus.de"
UTM = "?utm_source=email&utm_campaign=stb_outreach_seq1&utm_medium=cold_email"

# ============================================================
# HTML TEMPLATE
# ============================================================

SIGNATUR = f"""<br>
<table cellpadding="0" cellspacing="0" style="font-family:Arial,sans-serif;">
<tr><td style="padding:16px 0 0 0;border-top:1px solid #E2E8F0;">
<p style="margin:0;font-size:14px;line-height:1.6;color:#1E293B;">
<strong style="color:#003856;">Luis Schenk</strong><br>
<span style="color:#64748B;">Digitalisierung &amp; KI</span><br>
<span style="color:#64748B;">SBS Deutschland GmbH &amp; Co. KG</span><br>
<span style="color:#64748B;">Tel: {TELEFON}</span><br>
<a href="{WEBSITE}" style="color:#003856;text-decoration:none;">{WEBSITE}</a>
&nbsp;&middot;&nbsp;
<a href="{LINKEDIN}" style="color:#003856;text-decoration:none;">LinkedIn</a>
</p>
</td></tr>
</table>"""

OPT_OUT = """<p style="font-size:11px;color:#94A3B8;margin-top:24px;padding-top:12px;border-top:1px solid #F1F5F9;">
Wenn Sie keine weiteren Nachrichten wuenschen, antworten Sie kurz mit STOP.</p>"""


def email_html(paragraphs, cta_text=None):
    body = ""
    for p in paragraphs:
        body += f'<p style="font-family:Arial,sans-serif;font-size:15px;line-height:1.7;color:#1E293B;margin:0 0 14px 0;">{p}</p>\n'
    cta = ""
    if cta_text:
        cta = f"""<p style="margin:24px 0 8px 0;">
<a href="{CALENDLY}{UTM}" style="background-color:#003856;color:#ffffff;padding:12px 28px;
text-decoration:none;border-radius:6px;font-family:Arial,sans-serif;font-size:14px;
font-weight:bold;display:inline-block;">{cta_text}</a></p>"""
    return f'<div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif;">\n{body}{cta}{SIGNATUR}{OPT_OUT}\n</div>'


# ============================================================
# 7 PRIO-A E-MAILS
# ============================================================

EMAILS = [
    # BATCH 1: HEIMATMARKT
    {
        "batch": 1, "to": "info@stbstaat.de",
        "name": "Steuerberater Tobias Staat", "stadt": "Weinheim",
        "subject": "70% weniger Zeitaufwand bei der Rechnungsverarbeitung \u2013 f\u00fcr Ihre Kanzlei",
        "html": email_html([
            "Sehr geehrter Herr Staat,",
            "Ihre Kanzlei ist mir aufgefallen \u2013 als mehrfach ausgezeichnete digitale Steuerkanzlei in Weinheim und Heidelberg setzen Sie Ma\u00dfst\u00e4be, die im Markt selten sind. Besonders Ihr Ansatz \u201eSteuern gestalten, nicht verwalten\u201c hat mich angesprochen.",
            "Genau dort setzt SBS Nexus an: Unsere KI-gest\u00fctzte Rechnungsverarbeitung erkennt Rechnungsdaten in 8 Sekunden mit 99,2% Genauigkeit \u2013 und exportiert direkt DATEV-konform. Kanzleien wie Ihre, die bereits digital arbeiten, erzielen damit bis zu 70% Zeitersparnis bei der Belegverarbeitung.",
            "F\u00fcr Sie als Kanzlei mit Fokus auf Verm\u00f6gensgestaltung und KMU-Beratung bedeutet das: Mehr Zeit f\u00fcr die qualifizierte Beratung, die Ihre Mandanten sch\u00e4tzen \u2013 weniger Zeit f\u00fcr Routinearbeit.",
            "Als Weinheimer Unternehmen w\u00fcrden wir Ihnen gerne in 20 Minuten zeigen, wie das konkret f\u00fcr Ihre Kanzlei aussieht.",
        ], "20-Minuten-Demo buchen"),
    },
    {
        "batch": 1, "to": "kanzlei@hrsteuer.de",
        "name": "HR Steuerberatung", "stadt": "Mannheim",
        "subject": "KI-Rechnungsverarbeitung f\u00fcr HR Steuerberatung \u2013 passt zu Ihrem Digital-Ansatz",
        "html": email_html([
            "Sehr geehrte Damen und Herren,",
            "Auf Ihrer Website ist mir Ihre Sektion \u201eKI-Tools\u201c aufgefallen \u2013 das zeigt mir, dass Sie Technologie nicht nur nutzen, sondern aktiv vorantreiben. Genau solche Kanzleien suchen wir als Partner.",
            "SBS Nexus verarbeitet Eingangsrechnungen in 8 Sekunden mit 99,2% Genauigkeit \u2013 XRechnung, ZUGFeRD und PDF. Der DATEV-Export erfolgt automatisch. F\u00fcr Ihre Mandanten aus dem Onlinehandel, die oft hunderte Rechnungen pro Monat haben, ist das besonders relevant.",
            "Als Kanzlei-Partner erhalten Sie 15-25% Revenue Share \u2013 dauerhaft, ohne Vorabkosten.",
            "Wir sind ebenfalls in der Region und w\u00fcrden uns \u00fcber einen kurzen Austausch freuen.",
        ], "20-Minuten-Demo buchen"),
    },
    {
        "batch": 1, "to": "info@treuhand-heidelberg.de",
        "name": "Treuhand Heidelberg StBG mbH", "stadt": "Weinheim",
        "subject": "Digitale Zusammenarbeit neu gedacht \u2013 f\u00fcr Treuhand Heidelberg",
        "html": email_html([
            "Sehr geehrte Damen und Herren,",
            "Als Nachbarn in Weinheim freue ich mich, Ihnen eine L\u00f6sung vorzustellen, die perfekt zu Ihrem digitalen Kanzlei-Ansatz passt. Sie betonen auf Ihrer Website die Vorteile digitaler Zusammenarbeit mit Mandanten \u2013 SBS Nexus erweitert diese M\u00f6glichkeiten.",
            "Unsere KI-Rechnungsverarbeitung erkennt Rechnungsdaten in 8 Sekunden mit 99,2% Genauigkeit und exportiert direkt DATEV-konform. F\u00fcr Ihre Mandanten bedeutet das: Belege digital bereitstellen und sofort verarbeiten lassen, statt auf manuelle Buchung zu warten.",
            "Als Partner-Kanzlei verdienen Sie 15-25% Revenue Share auf jeden Mandanten, der SBS Nexus nutzt. Dauerhaft, ohne Vorabkosten.",
            "Da wir beide in Weinheim sitzen, schlage ich ein pers\u00f6nliches Treffen vor \u2013 gerne auch bei Ihnen in der Institutstra\u00dfe.",
        ], "Termin buchen"),
    },

    # BATCH 2: FRANKFURT
    {
        "batch": 2, "to": "kanzlei@steuba.de",
        "name": "STEUBA GmbH", "stadt": "Frankfurt",
        "subject": "DATEV Unternehmen Online + KI: 70% schnellere Belegverarbeitung f\u00fcr STEUBA",
        "html": email_html([
            "Sehr geehrter Herr Jonas,",
            "Als STEUBA GmbH setzen Sie bereits auf DATEV Unternehmen Online f\u00fcr Ihre Mandanten \u2013 und beschreiben sich selbst als Steuerberatung mit Hands-on-Mentalit\u00e4t. Das hat mich direkt angesprochen.",
            "Genau da setzt SBS Nexus an: Unsere KI-Rechnungsverarbeitung integriert sich nahtlos in DATEV und verarbeitet Eingangsrechnungen in 8 Sekunden \u2013 egal ob XRechnung, ZUGFeRD oder gescanntes PDF. Erkennungsgenauigkeit: 99,2%.",
            "F\u00fcr Ihre Start-up-Mandanten, die oft schnell wachsen und Rechnungsvolumina steigen, ist das ein echter Hebel: Weniger manuelle Arbeit bei gleichzeitig steigender Qualit\u00e4t.",
            "Als Partner-Kanzlei erhalten Sie 15-25% Revenue Share auf jeden vermittelten Mandanten \u2013 dauerhaft.",
        ], "20-Minuten-Demo buchen"),
    },
    {
        "batch": 2, "to": "info@luebeckonline.com",
        "name": "Steuerkanzlei L\u00dcBECK", "stadt": "Frankfurt",
        "subject": "Digitale DATEV-Kanzlei seit 2019 \u2013 der n\u00e4chste Schritt: KI-Rechnungsverarbeitung",
        "html": email_html([
            "Sehr geehrte Damen und Herren,",
            "Ihre Kanzlei tr\u00e4gt das Label Digitale DATEV-Kanzlei seit 2019 \u2013 damit geh\u00f6ren Sie zu den absoluten Vorreitern in Frankfurt. Genau solche Kanzleien suchen wir als Partner f\u00fcr den n\u00e4chsten Digitalisierungsschritt.",
            "SBS Nexus bringt KI-gest\u00fctzte Rechnungsverarbeitung, die \u00fcber das hinausgeht, was DATEV Unternehmen Online allein leisten kann: 99,2% Erkennungsgenauigkeit, automatischer DATEV-Export, 8 Sekunden pro Rechnung \u2013 f\u00fcr XRechnung, ZUGFeRD und PDF.",
            "Als Digitale Kanzlei k\u00f6nnen Sie das Ihren Mandanten als Premium-Service anbieten und dabei 15-25% Revenue Share verdienen \u2013 dauerhaft, ohne Vorabkosten.",
        ], "20-Minuten-Demo buchen"),
    },

    # BATCH 3: STUTTGART + KOELN
    {
        "batch": 3, "to": "info@steuerboard-stuttgart.de",
        "name": "STEUERBOARD Stuttgart", "stadt": "Stuttgart",
        "subject": "7x Digitale DATEV-Kanzlei \u2013 bereit f\u00fcr den KI-Vorsprung?",
        "html": email_html([
            "Sehr geehrte Damen und Herren,",
            "Sieben Mal in Folge als Digitale DATEV-Kanzlei ausgezeichnet \u2013 das ist nicht nur beeindruckend, es zeigt eine konsequente Haltung zur Digitalisierung, die im Markt selten ist.",
            "Mit SBS Nexus bieten wir den n\u00e4chsten logischen Schritt: KI-gest\u00fctzte Rechnungsverarbeitung, die Ihre bestehenden DATEV-Prozesse nicht ersetzt, sondern erweitert. 99,2% Erkennungsgenauigkeit, automatischer DATEV-Export, 8 Sekunden pro Rechnung.",
            "F\u00fcr eine Kanzlei mit Ihrem Digitalisierungsgrad ist das besonders spannend: Sie k\u00f6nnen Ihren Mandanten ein KI-Tool anbieten, das andere Kanzleien noch nicht haben. Ihr 7. Label wird zum Wettbewerbsvorteil.",
            "Als Partner verdienen Sie 15-25% Revenue Share \u2013 dauerhaft, ohne Vorabkosten.",
        ], "20-Minuten-Demo buchen"),
    },
    {
        "batch": 3, "to": "info@steuberludwig.de",
        "name": "Steuber Ludwig StB PartG mbB", "stadt": "K\u00f6ln",
        "subject": "Keine Papiermandate + KI: Passt SBS Nexus zu Steuber Ludwig?",
        "html": email_html([
            "Sehr geehrte Damen und Herren,",
            "Ihre konsequente Haltung hat mich beeindruckt: Keine Papiermandate, digitales Onboarding bei Mandatsaufnahme, und Sie erw\u00e4hnen explizit den Einsatz von KI in der Steuerberatung. Das ist in der Branche noch die Ausnahme.",
            "SBS Nexus ist genau f\u00fcr Kanzleien wie Ihre entwickelt: KI-gest\u00fctzte Rechnungsverarbeitung mit 99,2% Erkennungsgenauigkeit, automatischem DATEV-Export und Verarbeitung in 8 Sekunden \u2013 XRechnung, ZUGFeRD, PDF.",
            "Was uns unterscheidet: Wir bieten echte multimodale KI, nicht regelbasierte OCR. Das bedeutet auch bei komplexen Layouts, handschriftlichen Erg\u00e4nzungen und internationalen Rechnungen zuverl\u00e4ssige Ergebnisse.",
            "Als Partner-Kanzlei erhalten Sie 15-25% Revenue Share und einen Technologie-Vorsprung, den Ihre Mandanten sp\u00fcren.",
        ], "20-Minuten-Demo buchen"),
    },
]


# ============================================================
# API + SEND LOGIC
# ============================================================


def send_email(e, test_mode=False):
    to = TEST_EMAIL if test_mode else e["to"]
    payload = {
        "from": f"{FROM_NAME} <{FROM_EMAIL}>",
        "to": [to],
        "reply_to": REPLY_TO,
        "subject": e["subject"],
        "html": e["html"],
        "tags": [
            {"name": "campaign", "value": "stb_outreach_seq1"},
            {"name": "prospect", "value": e["name"].replace(" ", "_")},
            {"name": "batch", "value": str(e["batch"])},
        ]
    }
    try:
        r = requests.post("https://api.resend.com/emails", headers=resend_headers(), json=payload, timeout=15)
        if r.status_code in [200, 201]:
            return {"ok": True, "id": r.json().get("id", "?")}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text}"}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def preview(batch=None):
    print(f"\n{'='*60}")
    print(f"  SBS NEXUS \u2014 Outreach Preview")
    print(f"{'='*60}")
    for i, e in enumerate(EMAILS, 1):
        if batch and e["batch"] != batch:
            continue
        print(f"\n  #{i} | {e['name']} ({e['stadt']})")
        print(f"  An:      {e['to']}")
        print(f"  Betreff: {e['subject']}")
        print(f"  Batch:   {e['batch']}")
    n = len([e for e in EMAILS if not batch or e["batch"] == batch])
    print(f"\n  {n} E-Mails bereit.\n")


def send_all(batch=None, test_mode=False):
    emails = [e for e in EMAILS if not batch or e["batch"] == batch]
    mode = "TEST" if test_mode else "LIVE"
    print(f"\n{'='*60}")
    print(f"  SBS NEXUS \u2014 Outreach Sender [{mode}]")
    print(f"  {len(emails)} E-Mails | Von: {FROM_EMAIL}")
    if test_mode:
        print(f"  Alle gehen an: {TEST_EMAIL}")
    print(f"{'='*60}\n")

    if not test_mode:
        print("  LIVE-MODUS: E-Mails gehen an echte Empfaenger!")
        if input("  Fortfahren? Tippe 'ja': ").strip().lower() != "ja":
            print("  Abgebrochen.\n")
            return
        print()

    ok, fail, log = 0, 0, []
    for i, e in enumerate(emails, 1):
        to_show = TEST_EMAIL if test_mode else e["to"]
        print(f"  [{i}/{len(emails)}] {e['name']} -> {to_show}")
        result = send_email(e, test_mode)
        if result["ok"]:
            print(f"         Gesendet (ID: {result['id']})")
            ok += 1
            log.append({"ok": True, "to": to_show, "name": e["name"], "id": result["id"]})
        else:
            print(f"         FEHLER: {result['error']}")
            fail += 1
            log.append({"ok": False, "to": to_show, "name": e["name"], "error": result["error"]})
        if i < len(emails):
            print(f"         Pause 10s...")
            time.sleep(10)
        print()

    # Log
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        logdir = "/var/www/invoice-app/logs"
        os.makedirs(logdir, exist_ok=True)
        logfile = f"{logdir}/outreach_{ts}.json"
        with open(logfile, "w") as f:
            json.dump({"ts": ts, "mode": mode, "batch": batch, "results": log}, f, indent=2, ensure_ascii=False)
        print(f"  Log: {logfile}")
    except:
        pass

    print(f"\n{'='*60}")
    print(f"  ERGEBNIS: {ok} gesendet, {fail} fehlgeschlagen")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    if ok > 0 and not test_mode:
        print(f"\n  Naechste Schritte:")
        print(f"  -> CRM-Status auf 'E-Mail 1 gesendet' setzen")
        print(f"  -> In 3 Tagen: Follow-up E-Mail 2")
        print(f"  -> Resend Dashboard: https://resend.com/emails")
    print()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SBS Nexus Outreach Sender")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--send-test", action="store_true", help="Test an luis@schenk.com")
    p.add_argument("--send", action="store_true", help="LIVE senden")
    p.add_argument("--batch", type=int, choices=[1,2,3])
    args = p.parse_args()

    if args.preview:
        preview(args.batch)
    elif args.send_test:
        send_all(args.batch, test_mode=True)
    elif args.send:
        send_all(args.batch, test_mode=False)
    else:
        p.print_help()
        print("\nBeispiele:")
        print("  python3 sbs_outreach_sender.py --preview")
        print("  python3 sbs_outreach_sender.py --send-test")
        print("  python3 sbs_outreach_sender.py --send --batch 1")
        print("  python3 sbs_outreach_sender.py --send")
