# PowerShell script to connect to production database for verification
# Usage: .\connect_to_prod.ps1

# Set connection variables
$env:PGHOST = "prd-wiser-psql.postgres.database.usgovcloudapi.net"
$env:PGUSER = "wiserpgadmin"
$env:PGPORT = "5432"
$env:PGDATABASE = "postgres"
$env:PGPASSWORD = "DauUhbv74u5QXm2"

# Optional: Add SSL mode if required
# $env:PGSSLMODE = "require"

Write-Host "Connecting to production database..."
Write-Host "Host: $env:PGHOST"
Write-Host "Database: $env:PGDATABASE"
Write-Host "User: $env:PGUSER"
Write-Host ""
Write-Host "Running schema check queries..."
Write-Host ""

# Run the schema check SQL file
psql -f PRODUCTION_SCHEMA_CHECK.sql

Write-Host ""
Write-Host "Schema check complete!"
Write-Host "Review the results above and check PRODUCTION_VERIFICATION_GUIDE.md for next steps."

