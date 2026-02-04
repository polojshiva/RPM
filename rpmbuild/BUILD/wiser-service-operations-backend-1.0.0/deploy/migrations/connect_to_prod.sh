#!/bin/bash
# Script to connect to production database for verification
# Usage: ./connect_to_prod.sh

# Set connection variables
export PGHOST=prd-wiser-psql.postgres.database.usgovcloudapi.net
export PGUSER=wiserpgadmin
export PGPORT=5432
export PGDATABASE=postgres
export PGPASSWORD=DauUhbv74u5QXm2

# Optional: Add SSL mode if required
# export PGSSLMODE=require

echo "Connecting to production database..."
echo "Host: $PGHOST"
echo "Database: $PGDATABASE"
echo "User: $PGUSER"
echo ""
echo "Running schema check queries..."
echo ""

# Run the schema check SQL file
psql -f PRODUCTION_SCHEMA_CHECK.sql

echo ""
echo "Schema check complete!"
echo "Review the results above and check PRODUCTION_VERIFICATION_GUIDE.md for next steps."

