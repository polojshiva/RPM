# Async/Sync I/O Flow Explanation

## Overview: How Everything Works Together

This document explains the async/sync I/O flow, where blocking happens, and how it affects user requests.

---

## Architecture Layers

### 1. **FastAPI/Uvicorn Event Loop (Async)**
- **What:** Main async event loop handling all HTTP requests
- **Threads:** Runs in main thread, uses async/await
- **Handles:** User requests (login, API calls), background task coordination

### 2. **Background Tasks (Async Loop)**
- **What:** Async polling loops for message processing
- **Threads:** Runs in same event loop as user requests
- **Handles:** Polling database, coordinating work

### 3. **Thread Pool Executor (Sync Operations)**
- **What:** Default Python ThreadPoolExecutor (~32 threads)
- **Threads:** Separate threads for blocking I/O
- **Handles:** Database queries, blob downloads, OCR calls, PDF processing

---

## Complete Flow: Message Poller Processing

### Step 1: Poll Loop (Async)
```python
async def _poll_loop(self):
    while self.is_running:
        await self._poll_and_process()  # Async
        await asyncio.sleep(180)  # Non-blocking sleep
```

**What happens:**
- ✅ **Non-blocking** - uses `await asyncio.sleep()`
- ✅ Event loop can handle user requests during sleep
- ✅ No threads used

---

### Step 2: Poll for New Messages (Sync in Executor)
```python
messages = await loop.run_in_executor(
    None,  # Use default ThreadPoolExecutor
    inbox_service.poll_new_messages,  # SYNC function
    batch_size
)
```

**What happens:**
- 🔄 **Blocks a thread** (not event loop)
- 🔄 Executes sync database query: `SELECT * FROM integration.send_serviceops`
- ⏱️ **Duration:** ~0.1-1 second
- ✅ Event loop continues handling user requests
- ✅ Thread released when query completes

**Thread usage:** 1 thread for ~1 second

---

### Step 3: Insert Messages into Inbox (Sync in Executor)
```python
for msg in messages:  # Loop through 7 messages
    inbox_id = await loop.run_in_executor(
        None,
        inbox_service.insert_into_inbox,  # SYNC function
        ...
    )
```

**What happens:**
- 🔄 **Blocks a thread** for each insert
- 🔄 Executes sync database INSERT: `INSERT INTO integration_inbox ... ON CONFLICT DO NOTHING`
- ⏱️ **Duration:** ~0.05-0.2 seconds per insert
- ✅ Event loop continues handling user requests
- ✅ Thread released after each insert

**Thread usage:** 1 thread × 7 messages = 7 sequential operations (~1-2 seconds total)

---

### Step 4: Process Claimed Jobs (The Heavy Part)
```python
for iteration in range(max_jobs_per_cycle):  # Up to 4-5 jobs
    job = await loop.run_in_executor(None, inbox_service.claim_job, ...)
    source_msg = await loop.run_in_executor(None, inbox_service.get_source_message, ...)
    
    # Process message - THIS IS THE BLOCKING PART
    await self._process_message(...)
    
    await loop.run_in_executor(None, status_update_service.mark_done_with_retry, ...)
    await asyncio.sleep(3.0)  # Delay between jobs
```

**What happens:**
- 🔄 Each `run_in_executor` call blocks a thread
- ⏱️ **Duration:** Varies by operation

---

### Step 5: Document Processing (BLOCKING I/O - 20-110 seconds)
```python
# Inside _process_intake_message():
await loop.run_in_executor(
    None,
    processor.process_message,  # SYNC function - BLOCKS THREAD
    message,
    inbox_id
)
```

**What `process_message()` does (ALL BLOCKING):**

1. **Database Operations (Sync):**
   - Get/create packet: `SELECT/INSERT` - **~0.1s**
   - Get/create document: `SELECT/INSERT` - **~0.1s**
   - **Thread blocked:** ~0.2s

2. **Blob Downloads (BLOCKING I/O):**
   ```python
   # Inside DocumentProcessor:
   blob_client.download_to_temp(...)  # SYNC - blocks thread
   ```
   - Downloads PDFs from Azure Blob Storage
   - **Thread blocked:** **5-30 seconds** (depends on file size)
   - Network I/O is blocking - thread waits for download

3. **PDF Processing (CPU-bound):**
   ```python
   pdf_merger.merge(...)  # SYNC - blocks thread
   document_splitter.split(...)  # SYNC - blocks thread
   ```
   - Merges PDFs, splits into pages
   - **Thread blocked:** **5-20 seconds** (CPU intensive)

4. **Blob Uploads (BLOCKING I/O):**
   ```python
   blob_client.upload_file(...)  # SYNC - blocks thread
   ```
   - Uploads consolidated PDF and page PDFs
   - **Thread blocked:** **5-30 seconds** (depends on file size)

5. **OCR Service Calls (BLOCKING HTTP I/O):**
   ```python
   # Inside OCRService:
   response = requests.post(ocr_url, ...)  # SYNC - blocks thread
   ```
   - HTTP POST to OCR service for each page
   - **Thread blocked:** **10-60 seconds** per page (sequential)
   - For 10 pages: **100-600 seconds total** (but done sequentially)

6. **Database Updates (Sync):**
   - Update packet_document with OCR results
   - **Thread blocked:** **~0.1s**

**Total thread blocking time per job: 20-110 seconds**

---

## Thread Pool Exhaustion Scenario

### With 4 Workers, Batch Size 4:

**Worker 1:**
- Job 1: Thread blocked for 60s (blob download + OCR)
- Job 2: Thread blocked for 45s
- Job 3: Thread blocked for 80s
- Job 4: Thread blocked for 50s
- **Total: 4 threads blocked for 60-80 seconds**

**Worker 2:**
- Same pattern: 4 threads blocked

**Worker 3:**
- Same pattern: 4 threads blocked

**Worker 4:**
- Same pattern: 4 threads blocked

**Total threads used:** 16 threads blocked for 20-110 seconds each

**Default ThreadPoolExecutor:** ~32 threads

**Available for user requests:** ~16 threads

---

## User Request Flow (Login Example)

### Step 1: User Makes Login Request
```python
# FastAPI route (async)
@router.post("/api/auth/login")
async def login(request: Request):
    # This runs in event loop - NOT blocking
    user = await get_current_user(request)
    return {"status": "ok"}
```

**What happens:**
- ✅ Runs in async event loop
- ✅ No threads used initially
- ✅ Can handle thousands of concurrent requests (event loop is efficient)

---

### Step 2: Token Validation (Async)
```python
async def verify_token(token: str):
    # Fetch JWKS keys (async HTTP)
    jwks_data = await _fetch_jwks()  # Async HTTP call
    
    # Verify token (CPU-bound, but fast)
    claims = jwt.decode(token, ...)  # ~0.01s CPU
```

**What happens:**
- ✅ Uses async HTTP (`httpx.AsyncClient`)
- ✅ **Non-blocking** - event loop handles it
- ⏱️ **Duration:** ~0.5-2 seconds (network I/O, but async)
- ✅ No threads blocked

---

### Step 3: Database User Lookup (If Needed)
```python
# If user info needs to be fetched from DB:
db = SessionLocal()  # Gets connection from pool
user = db.query(User).filter(...).first()  # SYNC query
```

**What happens:**
- 🔄 **Blocks a thread** (if using sync SQLAlchemy)
- ⏱️ **Duration:** ~0.05-0.2 seconds
- ✅ Thread released quickly
- ✅ Connection returned to pool

**Thread usage:** 1 thread for ~0.2 seconds

---

## The Problem: Thread Pool Contention

### Scenario: 4 Workers Processing, User Tries to Login

**Background tasks using threads:**
- 16 threads blocked for 20-110 seconds each (document processing)

**User login needs:**
- 1 thread for database query (~0.2s)

**Available threads:**
- 32 total - 16 used = **16 available**

**Result:** ✅ **User can login** (16 threads available)

---

### Worst Case: All 16 Jobs Start Simultaneously

**Timeline:**
- T=0s: 16 threads blocked (all jobs start)
- T=0.2s: User login request arrives
- **Available threads:** 32 - 16 = 16 ✅
- User login gets thread immediately ✅

---

## Why Batch Size 3-4 is Safe

### With Batch Size 4:
- **Max concurrent jobs:** 4 per worker × 4 workers = **16 jobs**
- **Max threads used:** 16 threads
- **Threads available:** 32 - 16 = **16 threads**
- **User requests:** Need 1-2 threads each
- **Result:** ✅ Plenty of threads for users

### With Batch Size 10 (Too High):
- **Max concurrent jobs:** 10 per worker × 4 workers = **40 jobs**
- **Max threads needed:** 40 threads
- **Threads available:** 32 - 40 = **-8 threads** ❌
- **Result:** ❌ **Thread pool exhausted - user requests wait**

---

## Key Points

### ✅ What's Async (Non-blocking):
1. **Event loop:** FastAPI routes, async functions
2. **HTTP calls:** `httpx.AsyncClient` (async)
3. **Sleep:** `asyncio.sleep()` (non-blocking)
4. **Coordination:** Async polling loops

### 🔄 What's Sync in Executor (Blocks Thread, Not Event Loop):
1. **Database queries:** SQLAlchemy sync operations
2. **Blob downloads:** Azure SDK sync operations
3. **OCR HTTP calls:** `requests.post()` (sync)
4. **PDF processing:** CPU-bound operations

### ⚠️ The Critical Path:
- **Document processing** blocks threads for **20-110 seconds**
- This is the main bottleneck
- Batch size limits concurrent blocking operations
- 3-second delay between jobs helps release threads

---

## Current Protection Mechanisms

1. **Batch Size Limit:** Max 4-5 concurrent jobs per worker
2. **Delay Between Jobs:** 3 seconds to release threads
3. **Connection Pool Monitoring:** Throttles when pool critical
4. **Request Priority:** Auth requests get priority timeout (10s)
5. **Executor Usage:** Blocking I/O runs in threads, not event loop

---

## Summary

**Event Loop (Async):**
- Handles user requests efficiently
- Coordinates background tasks
- Never blocks (uses async I/O)

**Thread Pool (Sync Operations):**
- Handles blocking I/O (DB, blob, HTTP)
- Limited to ~32 threads
- Batch size 3-4 ensures threads available for users

**Result:** ✅ Users can login even during heavy processing (with batch size 3-4)
