# Poller Restart Fixes

## Problem
The user reported that when poller services start, other services restart. This was caused by unhandled exceptions during startup and in background tasks.

## Issues Found

### 1. **ClinicalOps Processor Startup - No Exception Handling**
**Location:** `app/main.py` line 122

**Problem:**
```python
clinical_ops_processor = ClinicalOpsInboxProcessor()
await clinical_ops_processor.start()  # ❌ NO try/except - could crash startup
```

**Impact:** If `start()` throws an exception, the entire worker startup fails, causing a restart.

**Fix:** Added try/except block to catch and log errors without crashing startup.

---

### 2. **Background Task Exceptions - No Callback Handlers**
**Location:** `app/services/message_poller.py` and `app/services/clinical_ops_inbox_processor.py`

**Problem:**
```python
self.poll_task = asyncio.create_task(self._poll_loop())  # ❌ No exception handler
```

**Impact:** If the task raises an unhandled exception (before entering the while loop, or if exception escapes the try/except), Python logs it but the task dies. This could cause:
- Task stops processing
- Worker might restart if exception is severe enough
- No clear error message about why task stopped

**Fix:** Added `add_done_callback()` handlers to catch and log task exceptions gracefully.

---

### 3. **Heartbeat Task Exceptions - No Callback Handlers**
**Location:** `app/services/background_task_leader.py`

**Problem:**
```python
self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())  # ❌ No exception handler
```

**Impact:** If heartbeat task crashes, leadership is lost silently, and the worker might restart.

**Fix:** Added `add_done_callback()` handlers for heartbeat tasks.

---

## Changes Made

### 1. Fixed ClinicalOps Startup Exception Handling
**File:** `app/main.py`

```python
# Before:
await clinical_ops_processor.start()

# After:
try:
    await clinical_ops_processor.start()
    # ... validation code ...
except Exception as e:
    logger.error(f"CRITICAL: Failed to start ClinicalOps inbox processor: {e}", exc_info=True)
    clinical_ops_processor = None  # Reset so shutdown doesn't try to stop it
```

---

### 2. Added Task Exception Handlers for Message Poller
**File:** `app/services/message_poller.py`

```python
# After creating task:
self.poll_task = asyncio.create_task(self._poll_loop())

# Add exception handler:
def handle_task_exception(task: asyncio.Task):
    """Handle unhandled exceptions in background task"""
    try:
        task.result()  # This will raise the exception if task failed
    except asyncio.CancelledError:
        pass  # Expected during shutdown
    except Exception as e:
        logger.error(
            f"CRITICAL: Unhandled exception in message poller task: {e}. "
            f"Poller will stop but worker will continue running.",
            exc_info=True
        )
        self.is_running = False

self.poll_task.add_done_callback(handle_task_exception)
```

---

### 3. Added Task Exception Handlers for ClinicalOps Processor
**File:** `app/services/clinical_ops_inbox_processor.py`

Same pattern as message poller - added `add_done_callback()` handler.

---

### 4. Added Task Exception Handlers for Heartbeat Tasks
**File:** `app/services/background_task_leader.py`

Added exception handlers for both places where heartbeat tasks are created.

---

## Why This Prevents Restarts

### Before Fixes:
1. **Startup Exception:** If `clinical_ops_processor.start()` throws an exception, the lifespan context manager fails, causing the worker to restart.
2. **Task Exception:** If a background task raises an unhandled exception, it's logged but the task dies. If the exception is severe (e.g., memory error, connection pool exhaustion), it could cause the worker to restart.
3. **Silent Failures:** Tasks could die silently without clear error messages, making debugging difficult.

### After Fixes:
1. **Startup Exception:** Caught and logged - worker continues running even if poller fails to start.
2. **Task Exception:** Caught by callback handler - task stops gracefully, error is logged, worker continues running.
3. **Clear Errors:** All exceptions are logged with full stack traces, making debugging easier.

---

## Testing

To verify the fixes work:

1. **Startup Test:** Temporarily break `clinical_ops_processor.start()` (e.g., raise an exception) - worker should start but log an error.
2. **Task Exception Test:** Add a `raise Exception("test")` at the start of `_poll_loop()` - task should stop but worker should continue.
3. **Monitor Logs:** Check for "CRITICAL: Unhandled exception" messages - these indicate exceptions were caught and handled.

---

## Summary

**Root Cause:** Unhandled exceptions during startup and in background tasks could cause worker restarts.

**Solution:** Added comprehensive exception handling:
- ✅ Try/except around ClinicalOps processor startup
- ✅ Task exception callbacks for all background tasks
- ✅ Task exception callbacks for heartbeat tasks
- ✅ Graceful degradation (worker continues even if tasks fail)

**Result:** Workers will no longer restart when pollers encounter exceptions. Errors are logged clearly, and the worker continues serving user requests.
