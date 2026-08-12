# OrbitalMind — PostgreSQL 16 + PostGIS Setup (Windows 11)

Complete step-by-step setup guide for the OrbitalMind spatial database on Windows 11.
Estimated time: **30–45 minutes**.

---

## Prerequisites

- Windows 11 (64-bit)
- Administrator privileges
- ~3 GB free disk space (PostgreSQL + PostGIS + Kerala OSM data)
- Internet connection for downloads

> **Note:** The OrbitalMind health check detected **PostgreSQL 18.4** already installed.
> Skip to [Step 2](#step-2-create-the-orbitalmind-database) if PostgreSQL is already running.

---

## Step 1 — Install PostgreSQL 16

### 1a. Download the installer

Go to https://www.enterprisedb.com/downloads/postgres-postgresql-downloads and download:
`postgresql-16.x-windows-x64.exe`

### 1b. Run installer

Accept all defaults **except**:
- **Password**: set `postgres` (match what the app expects)
- **Port**: `5432` (default)
- ✅ **Check "StackBuilder"** — needed for PostGIS in the next step

### 1c. Add PostgreSQL to PATH (required for psql / pg_ctl)

Open PowerShell as Administrator:
```powershell
$pgbin = "C:\Program Files\PostgreSQL\16\bin"
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$pgbin", "Machine")
# Restart PowerShell after this
```

Verify:
```powershell
psql --version
# Expected: psql (PostgreSQL) 16.x
```

---

## Step 2 — Create the OrbitalMind Database

Open a new PowerShell terminal:

```powershell
# Connect as superuser
psql -U postgres -p 5432

# In psql shell:
CREATE DATABASE orbitalmind;
\c orbitalmind
CREATE EXTENSION IF NOT EXISTS postgis;
SELECT PostGIS_Full_Version();   -- should print PostGIS version
\q
```

---

## Step 3 — Enable PostGIS Extension

### Option A — via StackBuilder (recommended)

1. Open **StackBuilder** (Start Menu → PostgreSQL 16 → Application Stack Builder)
2. Select your PostgreSQL 16 installation
3. Expand **Spatial Extensions** → check **PostGIS x.x for PostgreSQL 16**
4. Install and let it complete

### Option B — via psql (if PostGIS is already installed)

```sql
psql -U postgres -d orbitalmind -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql -U postgres -d orbitalmind -c "CREATE EXTENSION IF NOT EXISTS postgis_topology;"
```

Verify PostGIS is active:
```sql
psql -U postgres -d orbitalmind -c "SELECT PostGIS_Full_Version();"
```

Expected output: `POSTGIS="3.x.x" GEOS="3.x.x" ...`

---

## Step 4 — Install osm2pgsql (via OSGeo4W)

osm2pgsql is the standard tool for loading OpenStreetMap data into PostgreSQL.

### 4a. Download OSGeo4W Network Installer

https://download.osgeo.org/osgeo4w/v2/osgeo4w-setup.exe

### 4b. Run installer

- Select **Advanced Install**
- Mirror: any (e.g., `http://download.osgeo.org/osgeo4w/`)
- Search for `osm2pgsql` → mark for install
- Accept dependencies → Install

### 4c. Add to PATH

```powershell
$osgeo = "C:\OSGeo4W\bin"
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$osgeo", "Machine")
```

Verify:
```powershell
osm2pgsql --version
# Expected: osm2pgsql version 1.x.x
```

### Alternative (Chocolatey)

```powershell
# If you have Chocolatey installed:
choco install osm2pgsql -y
```

---

## Step 5 — Download Kerala OSM Extract

Download the latest Kerala OSM PBF file from Geofabrik:

```powershell
# Create data directory
mkdir C:\Users\jaymi\Documents\OrbitalMind\data\osm
cd C:\Users\jaymi\Documents\OrbitalMind\data\osm

# Download (~75 MB)
Invoke-WebRequest -Uri "https://download.geofabrik.de/asia/india/kerala-latest.osm.pbf" `
    -OutFile "kerala-latest.osm.pbf" -UseBasicParsing
```

Or download manually via browser:
`https://download.geofabrik.de/asia/india/kerala-latest.osm.pbf`

---

## Step 6 — Import OSM Data into PostgreSQL

From PowerShell (takes ~3–8 minutes on an SSD):

```powershell
cd C:\Users\jaymi\Documents\OrbitalMind\data\osm

osm2pgsql `
    --database orbitalmind `
    --host localhost `
    --port 5432 `
    --username postgres `
    --password `
    --create `
    --slim `
    --tag-transform-script "" `
    kerala-latest.osm.pbf
```

Enter `postgres` when prompted for password.

> **Tip:** To avoid the password prompt, set `PGPASSWORD` env variable:
> ```powershell
> $env:PGPASSWORD = "postgres"
> ```

### Expected output

```
2024-xx-xx xx:xx:xx  Reading in file: kerala-latest.osm.pbf
2024-xx-xx xx:xx:xx  Processing: Node(x) Way(x) Relation(x)
2024-xx-xx xx:xx:xx  Osm2pgsql took x seconds overall.
```

---

## Step 7 — Run the OrbitalMind Schema

```powershell
cd C:\Users\jaymi\Documents\OrbitalMind

psql -U postgres -d orbitalmind -f db/schema.sql
```

Expected output: `CREATE TABLE` × 4, `CREATE INDEX` × 8, `CREATE TRIGGER` × 1.

---

## Step 8 — Import Kerala Admin Boundaries

```powershell
pip install geopandas sqlalchemy psycopg2-binary --quiet
python scripts/import_admin_zones.py
```

Expected output:
```
[OK] Downloaded Kerala districts GeoJSON (14 districts)
[OK] Inserted 14 districts into admin_zones
[OK] Total population loaded: 33,406,061
```

---

## Step 9 — Verify Everything

```powershell
psql -U postgres -d orbitalmind -f db/verify.sql
```

All counts should be **> 0**.

---

## Common Windows Errors and Fixes

### Error: `psql: error: connection to server on socket failed`

PostgreSQL service is not running.

```powershell
# Start the service
net start postgresql-x64-16

# Or via Services panel: Win+R → services.msc → postgresql-x64-16 → Start
```

---

### Error: `FATAL: password authentication failed for user "postgres"`

The `pg_hba.conf` requires password but your env doesn't have one set.

```powershell
# Set PGPASSWORD in the current session
$env:PGPASSWORD = "postgres"

# Or edit pg_hba.conf to use 'trust' for localhost (dev only):
notepad "C:\Program Files\PostgreSQL\16\data\pg_hba.conf"
# Change: host all all 127.0.0.1/32  scram-sha-256
# To:     host all all 127.0.0.1/32  trust
# Then restart: net stop postgresql-x64-16 && net start postgresql-x64-16
```

---

### Error: `ERROR: could not open extension control file ... postgis.control`

PostGIS is not installed for this PostgreSQL version.

```powershell
# Run StackBuilder and install PostGIS for PostgreSQL 16
# Start Menu → PostgreSQL 16 → Application Stack Builder
```

---

### Error: `osm2pgsql: error while loading shared libraries`

OSGeo4W DLLs are not on PATH.

```powershell
# Run osm2pgsql from the OSGeo4W shell instead:
C:\OSGeo4W\OSGeo4W.bat
# Then run osm2pgsql inside the OSGeo4W terminal
```

---

### Error: `could not connect to server: No such file or directory` (osm2pgsql)

Explicitly pass all connection parameters:

```powershell
osm2pgsql -d orbitalmind -H 127.0.0.1 -P 5432 -U postgres kerala-latest.osm.pbf
```

---

### Error: `out of memory` during osm2pgsql import

Increase PostgreSQL `work_mem` and `maintenance_work_mem`:

```sql
-- Run in psql as superuser:
ALTER SYSTEM SET work_mem = '256MB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';
SELECT pg_reload_conf();
```

---

### Port 5432 already in use

```powershell
# Find what's using port 5432
netstat -ano | findstr :5432

# Kill the process (replace PID):
taskkill /F /PID <PID>
```

---

## Quick Reference — Useful psql Commands

```sql
\l                      -- list all databases
\c orbitalmind          -- connect to orbitalmind
\dt                     -- list all tables
\d affected_zones       -- describe table structure
\d+ planet_osm_point    -- describe OSM table
SELECT COUNT(*) FROM planet_osm_point WHERE amenity = 'hospital';
```
