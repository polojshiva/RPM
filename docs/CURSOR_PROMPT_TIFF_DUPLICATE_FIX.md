# Cursor Prompt: TIFF Duplicate Pages Fix Approach

## Problem
Multi-page TIFFs ended up with the correct page count but every page was the same (duplicates). Root cause: the payload can list the same blob URL multiple times (e.g., one TIF repeated 9 times). The document processor was downloading and merging each entry, so the same file was merged N times and produced N identical pages.

## Fix Approach

### Solution: Deduplicate by `source_absolute_url` Before Downloading

**Location:** `app/services/document_processor.py` - In the merge step (around "Step 4: Download ALL payload documents")

**Implementation:**
1. **Before downloading:** Deduplicate `parsed.documents` by `source_absolute_url`
2. **Keep first occurrence:** When the same URL appears multiple times, only keep the first document entry
3. **Download deduplicated list:** Only download and merge `docs_to_merge` (not the full `parsed.documents`)
4. **Log deduplication:** Log warning when duplicates are found: `"Deduplicated documents by URL: N -> M (X duplicate(s) removed)"`

**Code Pattern:**
```python
# Deduplicate by source_absolute_url before downloading
docs_to_merge = []
seen_urls = set()
duplicate_count = 0

for doc in parsed.documents:
    if doc.source_absolute_url in seen_urls:
        duplicate_count += 1
        logger.info(f"Skipping duplicate document URL: {doc.source_absolute_url}")
    else:
        seen_urls.add(doc.source_absolute_url)
        docs_to_merge.append(doc)

if duplicate_count > 0:
    logger.info(f"Deduplicated documents by URL: {len(parsed.documents)} -> {len(docs_to_merge)} ({duplicate_count} duplicate(s) removed)")

# Then download and merge docs_to_merge (not parsed.documents)
```

### How It Works

1. **Payload parsing:** `parsed.documents` may contain multiple entries with same `source_absolute_url`
2. **Deduplication:** Before downloading, filter to keep only first occurrence of each unique URL
3. **Download:** Download only unique URLs (one download per unique blob)
4. **Merge:** Merge deduplicated list (each unique file merged once)
5. **Result:** Multi-page TIFFs produce correct number of distinct pages (not multiplied by duplicate count)

### Example

**Before Fix:**
- Payload: 3 entries, all pointing to same 3-page TIF URL
- Download: 3 downloads of same file
- Merge: Same file merged 3 times
- Result: 9 pages (all identical)

**After Fix:**
- Payload: 3 entries, all pointing to same 3-page TIF URL
- Deduplication: 3 → 1 (2 duplicates removed)
- Download: 1 download of the file
- Merge: File merged once
- Result: 3 pages (distinct, correct)

### Key Points

- **Deduplication happens BEFORE download** - prevents unnecessary downloads
- **First occurrence kept** - preserves document order and metadata
- **Works with multi-page TIFFs** - Each unique TIFF is processed once, all frames become distinct pages
- **No breaking changes** - Existing functionality preserved, only prevents duplicates

### Testing

- **Unit tests:** Verify deduplication logic removes duplicates correctly
- **Integration tests:** Create multi-page TIFFs, simulate duplicate URLs in payload, verify correct page count
- **Existing tests:** All multi-page TIFF tests should still pass

### Files to Modify

1. `app/services/document_processor.py` - Add deduplication before download step
2. Add unit tests for deduplication logic
3. Add integration test with real multi-page TIFFs and duplicate URLs
