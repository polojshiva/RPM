# Gunicorn Startup Command - Production Configuration

## ⚠️ CRITICAL: Update Azure App Service Startup Command

The current startup command uses `--max-requests 200`, which causes workers to restart after processing 200 requests. This causes:
- **Background tasks to stop** when workers restart
- **Gaps in processing** while new workers initialize
- **Application appears to stop working** after ~5 minutes

## ✅ Recommended Startup Command

Update the startup command in Azure Portal:
**Path**: App Service → Configuration → General settings → Startup Command

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:$PORT --timeout 300 --max-requests 0 --max-requests-jitter 0 --access-logfile - --error-logfile - --log-level info
```

### Key Changes:
1. **`--max-requests 0`** - Disables worker restarts (0 = no limit)
2. **`--max-requests-jitter 0`** - Disables jitter (not needed if max-requests is 0)
3. **`--timeout 300`** - 5 minute timeout for long-running operations
4. **`-w 4`** - 4 workers for load balancing

## Alternative: High max-requests (if you prefer periodic restarts)

If you want workers to restart periodically (e.g., for memory leak prevention), use:

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:$PORT --timeout 300 --max-requests 10000 --max-requests-jitter 1000 --access-logfile - --error-logfile - --log-level info
```

This restarts workers after ~10,000 requests (with jitter), which is much less frequent.

## Background Task Leader Election

The application now uses **database-based leader election** to ensure only ONE instance of background tasks runs across all workers. This means:
- ✅ Only one message poller runs (even with 4 workers)
- ✅ Only one ClinicalOps processor runs (even with 4 workers)
- ✅ Background tasks automatically restart if the leader worker dies
- ✅ No duplicate processing or contention

## Why This Fixes the Issue

**Before:**
- Workers restart after 200 requests
- Each worker runs its own poller (4 pollers = contention)
- When workers restart, pollers stop → gap in processing

**After:**
- Workers don't restart (or restart very infrequently)
- Only ONE poller runs (leader election)
- If leader worker dies, another worker automatically takes over
- No gaps in processing
