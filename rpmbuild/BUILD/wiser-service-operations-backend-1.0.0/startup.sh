#!/bin/bash
# Azure App Service startup script for Service Operations Backend
# This script is used by Azure App Service to start the application
#
# CRITICAL FIX: Override PYTHONPATH to prevent /agents/python from shadowing venv packages
# This is the recommended workaround for Azure Oryx bug where /agents/python packages
# are imported instead of the venv's packages (causing import errors)
# Reference: https://github.com/Microsoft/Oryx/issues/2685

# Get port from Azure environment variable (defaults to 8000)
PORT=${PORT:-8000}

# Export port for Python to use
export PORT

# Azure App Service paths
# Oryx may extract to /tmp first, then move to /home/site/wwwroot
# Try to find the app directory dynamically
if [ -d "/home/site/wwwroot/antenv" ]; then
    APP_ROOT="/home/site/wwwroot"
elif [ -d "$(pwd)/antenv" ]; then
    APP_ROOT="$(pwd)"
else
    # Try to find antenv in /tmp (Oryx extraction directory)
    TMP_APP=$(find /tmp -maxdepth 2 -type d -name "antenv" 2>/dev/null | head -1)
    if [ -n "$TMP_APP" ]; then
        APP_ROOT=$(dirname "$TMP_APP")
        echo "WARNING: Using temporary extraction directory: $APP_ROOT"
    else
        APP_ROOT="/home/site/wwwroot"
        echo "WARNING: Could not find app directory, using default: $APP_ROOT"
    fi
fi

VENV_ROOT="$APP_ROOT/antenv"
VENV_PYTHON="$VENV_ROOT/bin/python"
VENV_PIP="$VENV_ROOT/bin/pip"
VENV_GUNICORN="$VENV_ROOT/bin/gunicorn"

# Determine Python version for site-packages path
if [ -f "$VENV_PYTHON" ]; then
    PYTHON_VERSION=$($VENV_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.11")
else
    PYTHON_VERSION="3.11"
fi
VENV_SITE="$VENV_ROOT/lib/python$PYTHON_VERSION/site-packages"

# Fallback to system Python if venv doesn't exist (shouldn't happen in Azure)
if [ ! -f "$VENV_PYTHON" ]; then
    echo "WARNING: Venv Python not found at $VENV_PYTHON, using system Python"
    VENV_PYTHON="python"
    VENV_PIP="pip"
    VENV_GUNICORN="gunicorn"
    VENV_SITE=""
fi

# CRITICAL FIX: Override PYTHONPATH to exclude /agents/python
# Oryx sets PYTHONPATH with /agents/python first, which shadows venv packages
# We MUST override it AFTER Oryx sets it to ensure venv packages take precedence
# Build clean PYTHONPATH with only app root and venv site-packages (exclude /agents/python)
if [ -n "$VENV_SITE" ] && [ -d "$VENV_SITE" ]; then
    # Explicitly set PYTHONPATH to only what we want (overrides Oryx's setting)
    export PYTHONPATH="$APP_ROOT:$VENV_SITE"
else
    export PYTHONPATH="$APP_ROOT"
fi

# Prevent Python from using user site-packages (which might also have conflicts)
export PYTHONNOUSERSITE=1

# Log startup information
echo "=========================================="
echo "Starting Service Operations Backend..."
echo "PORT environment variable: $PORT"
echo "Python version: $($VENV_PYTHON --version)"
echo "Python path: $VENV_PYTHON"
echo "Working directory: $(pwd)"
echo "PYTHONPATH: $PYTHONPATH"
echo "PYTHONNOUSERSITE: $PYTHONNOUSERSITE"
echo "=========================================="

# Verify critical dependencies are installed
echo "Verifying critical dependencies..."
if [ -f "$APP_ROOT/requirements.txt" ]; then
    echo "Installing/updating dependencies from requirements.txt..."
    $VENV_PIP install --upgrade pip --quiet
    $VENV_PIP install -r "$APP_ROOT/requirements.txt" --quiet
    echo "✓ Dependencies installed"
else
    echo "WARNING: requirements.txt not found at $APP_ROOT/requirements.txt"
fi

# Verify Azure packages are installed
echo "Verifying Azure packages..."
if $VENV_PYTHON -c "import azure.storage.blob; print('✓ azure.storage.blob OK')" 2>/dev/null; then
    echo "✓ azure.storage.blob is installed"
else
    echo "ERROR: azure.storage.blob is NOT installed!"
    echo "Installing azure-storage-blob..."
    $VENV_PIP install azure-storage-blob --quiet
fi

if $VENV_PYTHON -c "import azure.identity; print('✓ azure.identity OK')" 2>/dev/null; then
    echo "✓ azure.identity is installed"
else
    echo "ERROR: azure.identity is NOT installed!"
    echo "Installing azure-identity..."
    $VENV_PIP install azure-identity --quiet
fi

# Verify other critical packages
echo "Verifying other critical packages..."
$VENV_PYTHON -c "import fastapi; print('✓ fastapi OK')" || echo "ERROR: fastapi import failed"
$VENV_PYTHON -c "import uvicorn; print('✓ uvicorn OK')" || echo "ERROR: uvicorn import failed"
$VENV_PYTHON -c "import pydantic; print('✓ pydantic OK')" || echo "ERROR: pydantic import failed"
$VENV_PYTHON -c "import sqlalchemy; print('✓ sqlalchemy OK')" || echo "ERROR: sqlalchemy import failed"
echo "=========================================="

# Change to app directory to ensure app/main.py can be found
cd "$APP_ROOT" || {
    echo "ERROR: Cannot change to app directory: $APP_ROOT"
    exit 1
}

# Start the application using gunicorn (recommended for production)
# Gunicorn is more stable than uvicorn for production workloads
# Use uvicorn workers to maintain async support
# CRITICAL: Increased timeout to 300s (5 minutes) to handle long-running OCR operations
# and document processing that can exceed the previous 120s timeout
echo "Starting gunicorn with uvicorn workers..."
$VENV_GUNICORN app.main:app \
    --bind 0.0.0.0:$PORT \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info






