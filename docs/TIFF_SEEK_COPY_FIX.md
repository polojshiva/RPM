# TIFF Seek+Copy Fix: Preventing Duplicate Pages

## Problem

When converting multi-page TIFFs to PDF, the output had the **correct page count** but **every page showed the same image** (e.g., 18 pages all showing page 1).

## Root Cause

**Pillow's `ImageSequence.Iterator` can yield shared references** to image data. Building a list with `list(ImageSequence.Iterator(img))` and then iterating that list later can result in all "frames" pointing to the same pixel data (e.g., the last or first frame). Using those references when creating PDF pages produces N identical pages.

## Fix

**Replaced `ImageSequence.Iterator` with `seek()` + `copy()` pattern** to ensure each frame has independent pixel data:

1. Open the TIFF with `PIL.Image.open(path)` and call `img.load()`.
2. **Build frames with `seek(i)` + `img.copy()`** in a loop until `EOFError`:
   ```python
   frames = []
   frame_idx = 0
   while True:
       try:
           img.seek(frame_idx)
           frames.append(img.copy())  # Independent copy of pixel data
           frame_idx += 1
       except EOFError:
           break
   ```
3. Use the `frames` list (each element is an independent copy) for creating PDF pages.

## Files Modified

### 1. `app/services/pdf_merger.py`
- **Method:** `_convert_tiff_to_pdf()`
- **Change:** Replaced `list(ImageSequence.Iterator(img))` with seek+copy loop
- **Impact:** Multi-page TIFFs now produce distinct PDF pages in merged output

### 2. `app/services/document_splitter.py`
- **Method:** `_split_tiff()`
- **Change:** Replaced `list(ImageSequence.Iterator(img))` with seek+copy loop
- **Impact:** Multi-page TIFFs now produce distinct single-page PDFs when split

## Testing

### Unit Tests
- **File:** `tests/test_tiff_distinct_pages.py`
- **Coverage:**
  - 3-page TIFF → 3 distinct pages
  - 5-page TIFF → 5 distinct pages
  - 9-page TIFF → 9 distinct pages (common problematic case)
  - 18-page TIFF → 18 distinct pages (another problematic case)
  - Split operation → distinct single-page PDFs
- **Verification:** Image hashing and pixel comparison to ensure pages are not duplicates

### Integration Tests
- **File:** `scripts/test_tiff_seek_copy_fix.py`
- **Scenarios:**
  1. Single multi-page TIFF → distinct pages
  2. Duplicate URLs in payload → deduplication + distinct pages
  3. Multiple unique TIFFs → correct total + distinct pages
  4. Large multi-page TIFFs (9, 18, 23 pages) → distinct pages
  5. Split operation → distinct single-page PDFs
- **Result:** All 5 integration tests pass

### Existing Tests
- **File:** `tests/test_tiff_multipage.py`
- **Status:** All 16 existing tests still pass (no regressions)

### Deduplication Tests
- **File:** `tests/test_document_processor_deduplication.py`
- **Status:** All tests pass, including distinct pages verification

## Verification

### Before Fix
- **Input:** 3-page TIFF
- **Output:** 3-page PDF with all pages showing the same image (duplicate)

### After Fix
- **Input:** 3-page TIFF
- **Output:** 3-page PDF with 3 distinct pages (verified by image hashing)

## Code Pattern

```python
# ❌ BAD — can produce N identical pages
frames = list(ImageSequence.Iterator(img))
for frame in frames:
    frame.save(...)  # may all be the same image

# ✅ GOOD — one distinct page per TIFF frame
frames = []
frame_idx = 0
while True:
    try:
        img.seek(frame_idx)
        frames.append(img.copy())  # independent copy
        frame_idx += 1
    except EOFError:
        break
for frame in frames:
    frame.save(...)  # each frame is distinct
```

## Related Fixes

- **Payload deduplication:** When merging documents from a payload, deduplicate by `source_absolute_url` before download/merge so the same blob URL listed N times does not produce N duplicate pages (see `docs/TIFF_DUPLICATE_PAGES_FIX.md`).

## Test Results

```
✅ 27 unit tests passed
✅ 5 integration tests passed
✅ All existing tests still pass (no regressions)
```

## Status

**FIXED:** Multi-page TIFFs now produce distinct pages (not duplicates). The seek+copy pattern ensures each frame has independent pixel data, preventing the shared reference issue with `ImageSequence.Iterator`.
