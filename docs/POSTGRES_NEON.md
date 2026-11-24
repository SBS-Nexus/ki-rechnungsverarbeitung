# PostgreSQL-Migration (Neon) – Setup & Betrieb

> Status: **Vorbereitung / Scaffolding.** Die Live-Datenbank
> (`/var/www/invoice-app/invoices.db`, SQLite) wird durch diese Schritte
> **nicht** automatisch verändert. Der eigentliche Cutover erfolgt
> kontrolliert und manuell (siehe unten).

## Überblick

Die modulare Architektur (`modules/`, `shared/`) ist auf PostgreSQL
ausgelegt. Mandantentrennung erfolgt über `tenant_id` auf jeder Tabelle
(`shared/tenant/context.py` liefert den aktuellen Tenant über einen
`ContextVar`).

- ORM: SQLAlchemy 2.x (`shared/db/session.py`)
- Migrationen: Alembic (`alembic.ini`, `migrations/`)
- Treiber: `psycopg` (v3), SSL für Neon erforderlich

## 1. Neon-Datenbank anlegen

1. Projekt auf [neon.tech](https://neon.tech) erstellen (Region z. B.
   `eu-central-1` für DSGVO-Nähe).
2. Connection-String kopieren und in das psycopg3-Format bringen:

   ```
   postgresql+psycopg://USER:PASSWORD@ep-xxxx.eu-central-1.aws.neon.tech/ki_rechnungsverarbeitung?sslmode=require
   ```

3. In die Umgebung legen (Produktion: `/etc/default/invoice-app`):

   ```bash
   DATABASE_URL="postgresql+psycopg://...sslmode=require"
   ```

## 2. Abhängigkeiten installieren

```bash
pip install -r requirements.txt   # enthält SQLAlchemy, alembic, psycopg[binary]
```

## 3. Migrationen prüfen (ohne DB-Verbindung)

Vorschau des erzeugten SQL – verbindet sich **nicht** mit der Datenbank:

```bash
DATABASE_URL="postgresql+psycopg://u:p@localhost/db" \
  python -m alembic upgrade head --sql
```

## 4. Migrationen ausführen (gegen Neon)

```bash
export DATABASE_URL="postgresql+psycopg://...sslmode=require"
python -m alembic upgrade head
```

Status / Historie:

```bash
python -m alembic current
python -m alembic history
```

## 5. Neue Migration erzeugen (nach Modell-Änderungen)

Modelle in `modules/.../db_models.py` anpassen, dann:

```bash
export DATABASE_URL="postgresql+psycopg://...sslmode=require"
python -m alembic revision --autogenerate -m "beschreibung"
```

> `migrations/env.py` importiert die Modelle und stellt `target_metadata`
> bereit – neue Modell-Module dort ergänzen, damit `--autogenerate` sie
> erkennt.

## 6. Datenmigration SQLite → Postgres (Cutover)

Der Legacy-Monolith (`web/app.py` + `database.py`) nutzt weiterhin SQLite.
Ein vollständiger Cutover umfasst:

1. Schema in Postgres anlegen (`alembic upgrade head`).
2. Bestandsdaten migrieren mit `scripts/migrate_sqlite_to_postgres.py`:

   ```bash
   # 1) Vorschau (Dry-Run, schreibt nichts, keine PG-Verbindung)
   python scripts/migrate_sqlite_to_postgres.py \
       --sqlite /var/www/invoice-app/invoices.db --tenant <TENANT>

   # 2) Tatsächliche Migration nach Neon
   export DATABASE_URL="postgresql+psycopg://...sslmode=require"
   python scripts/migrate_sqlite_to_postgres.py --tenant <TENANT> --commit
   ```

   Das Skript legt je Legacy-Rechnung einen Metadatensatz in `invoices`
   an (`status='migrated'`) und sichert die vollständigen Fachfelder
   verlustfrei als JSONB in `invoice_events` (event_type `legacy_import`).
   Es ist **idempotent** (bereits migrierte `document_id` werden
   übersprungen) und **Dry-Run per Default**.

3. `database.py`-Zugriffe schrittweise auf die SQLAlchemy-Session
   (`shared/db/session.py`) umstellen.
4. Service neu starten und Smoke-Tests fahren.

Der `--commit`-Schritt wird bewusst **nicht** automatisiert ausgeführt, um
Datenverlust auf der Produktiv-DB auszuschließen.
