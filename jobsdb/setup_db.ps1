# Bring up the local Postgres for the Aalto Job Library (Docker) and ingest data.
# Usage:  powershell -ExecutionPolicy Bypass -File jobsdb\setup_db.ps1
# Requires Docker Desktop running.

$ErrorActionPreference = "Stop"
$name = "aalto_pg"

# Start (or reuse) the container on port 5433 so it won't clash with a local PG.
if (-not (docker ps -a --filter "name=$name" --format "{{.Names}}")) {
    Write-Host "Creating Postgres container '$name' on port 5433..."
    docker run -d --name $name -e POSTGRES_PASSWORD=aalto -e POSTGRES_DB=aalto_jobs -p 5433:5432 postgres:16 | Out-Null
} else {
    Write-Host "Starting existing container '$name'..."
    docker start $name | Out-Null
}

# Wait for readiness.
for ($i = 0; $i -lt 30; $i++) {
    docker exec $name pg_isready -U postgres 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "Postgres ready."; break }
    Start-Sleep -Seconds 1
}

# Init schema + ingest the aerospace / competitor library.
python -m jobsdb.db
python -m jobsdb.ingest
Write-Host "`nDone. Launch the web UI with:  python -m jobsdb.app   (http://localhost:5000)"
