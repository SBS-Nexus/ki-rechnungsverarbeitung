#!/usr/bin/env python3
"""
KI-Rechnungsverarbeitung v2.0
Mit Better CLI, Colors & Progress Bar
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import pypdf
import pandas as pd
from datetime import datetime
import subprocess
import platform

# Rich für schöne CLI
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.panel import Panel
from rich import print as rprint

# Initialize
load_dotenv()
console = Console()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def print_header():
    """Schöner Header"""
    header = """
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║      🤖  KI-RECHNUNGSVERARBEITUNG v2.0  🤖             ║
    ║                                                          ║
    ║      Automatische PDF-Extraktion mit ChatGPT            ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """
    console.print(header, style="bold cyan")

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            reader = pypdf.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text()
        return text
    except Exception as e:
        console.print(f"❌ PDF Error: {e}", style="bold red")
        return None

def extract_invoice_data(text, filename):
    """Use ChatGPT to extract structured data"""
    
    prompt = f"""Extrahiere aus dieser Rechnung Daten als JSON:

{text[:3500]}

Format (nur JSON, keine Erklärungen):
{{
  "rechnungsnummer": "...",
  "datum": "YYYY-MM-DD",
  "lieferant": "...",
  "betrag_brutto": 123.45,
  "betrag_netto": 100.00,
  "mwst_betrag": 23.45,
  "iban": "..."
}}

Wenn Info fehlt: null setzen
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Du extrahierst Rechnungsdaten. Antworte nur mit JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )
        
        json_text = response.choices[0].message.content.strip()
        json_text = json_text.replace("```json", "").replace("```", "").strip()
        
        data = json.loads(json_text)
        data['dateiname'] = filename
        data['verarbeitet_am'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        return data
        
    except Exception as e:
        console.print(f"❌ API Error: {e}", style="bold red")
        return None

def process_invoice(pdf_path, task_id, progress):
    """Process single invoice"""
    progress.update(task_id, description=f"📄 [cyan]{pdf_path.name}[/cyan]")
    
    text = extract_text_from_pdf(pdf_path)
    if not text:
        return None
    
    progress.update(task_id, description=f"🤖 [yellow]KI analysiert...[/yellow]")
    
    data = extract_invoice_data(text, pdf_path.name)
    
    if data:
        lieferant = data.get('lieferant', '?')
        betrag = data.get('betrag_brutto', '?')
        progress.update(task_id, description=f"✅ [green]{lieferant} - {betrag}€[/green]")
    
    return data

def create_summary_table(results):
    """Create beautiful summary table"""
    table = Table(title="📊 Verarbeitete Rechnungen", show_header=True, header_style="bold magenta")
    
    table.add_column("#", style="dim", width=6)
    table.add_column("Lieferant", style="cyan")
    table.add_column("Datum", style="yellow")
    table.add_column("Betrag", justify="right", style="green")
    table.add_column("Status", justify="center")
    
    for i, result in enumerate(results, 1):
        lieferant = result.get('lieferant', 'N/A')
        datum = result.get('datum', 'N/A')
        betrag = f"{result.get('betrag_brutto', 0):.2f}€"
        status = "✅"
        
        table.add_row(str(i), lieferant, datum, betrag, status)
    
    return table

def main():
    """Hauptprogramm"""
    
    # Header
    print_header()
    
    # Check API Key
    if not os.getenv('OPENAI_API_KEY'):
        console.print("\n❌ [bold red]Fehler: OPENAI_API_KEY nicht in .env gefunden![/bold red]\n")
        return
    
    # Create folder if not exists
    folder = Path("test_rechnungen")
    if not folder.exists():
        folder.mkdir()
        console.print("✅ [green]Ordner 'test_rechnungen' erstellt[/green]")
        console.print("→ [yellow]Füge PDFs hinzu und starte neu![/yellow]\n")
        return
    
    # Find PDFs
    pdfs = list(folder.glob("*.pdf"))
    
    if not pdfs:
        console.print("❌ [red]Keine PDFs in 'test_rechnungen' gefunden![/red]")
        console.print("→ [yellow]Kopiere PDFs rein und starte neu![/yellow]\n")
        return
    
    console.print(f"\n🚀 [bold cyan]Starte Verarbeitung von {len(pdfs)} Rechnungen...[/bold cyan]\n")
    
    # Process all PDFs with progress bar
    results = []
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        
        task = progress.add_task("[cyan]Verarbeite...", total=len(pdfs))
        
        for pdf in pdfs:
            data = process_invoice(pdf, task, progress)
            if data:
                results.append(data)
            progress.advance(task)
    
    # Export to Excel
    if results:
        df = pd.DataFrame(results)
        output = "rechnungen_export.xlsx"
        df.to_excel(output, index=False)
        
        console.print("\n")
        console.print(create_summary_table(results))
        
        # Summary Panel
        total = df['betrag_brutto'].sum() if 'betrag_brutto' in df.columns else 0
        avg = df['betrag_brutto'].mean() if 'betrag_brutto' in df.columns else 0
        
        summary = f"""
        ✅ [bold green]Verarbeitung abgeschlossen![/bold green]
        
        📊 Ergebnisse:
           • Rechnungen: [cyan]{len(results)}[/cyan]
           • Gesamt: [green]{total:.2f}€[/green]
           • Durchschnitt: [yellow]{avg:.2f}€[/yellow]
        
        💾 Export: [cyan]{output}[/cyan]
        """
        
        console.print(Panel(summary, title="[bold]Zusammenfassung[/bold]", border_style="green"))
        
        # Excel automatisch öffnen
        try:
            if platform.system() == 'Darwin':  # Mac
                subprocess.run(['open', output], check=False)
            elif platform.system() == 'Windows':
                os.startfile(output)
            else:  # Linux
                subprocess.run(['xdg-open', output], check=False)
            
            console.print(f"\n📂 [cyan]Excel wurde automatisch geöffnet![/cyan]\n")
        except Exception as e:
            console.print(f"\n⚠️  [yellow]Excel konnte nicht geöffnet werden: {e}[/yellow]\n")
        
    else:
        console.print("\n❌ [red]Keine Rechnungen erfolgreich verarbeitet[/red]\n")

if __name__ == "__main__":
    main()
