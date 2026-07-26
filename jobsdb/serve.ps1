# Launch the Aalto Job Library web UI so it keeps running independently.
# Usage:  powershell -ExecutionPolicy Bypass -File jobsdb\serve.ps1
# Opens a detached window serving http://localhost:5000 and launches your browser.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

# Make sure the Docker DB is up.
if (docker ps -a --filter "name=aalto_pg" --format "{{.Names}}") {
    docker start aalto_pg | Out-Null
}

# Start the Flask app in its own window (survives this script exiting).
Start-Process -FilePath "python" -ArgumentList "-m","jobsdb.app" -WorkingDirectory $root
Start-Sleep -Seconds 3
Start-Process "http://localhost:5000"
Write-Host "Serving http://localhost:5000 in a separate window. Close that window to stop."
