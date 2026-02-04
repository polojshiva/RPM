# FAX Channel Container Extraction Fix - Deployment Summary

## Overview
This document outlines the **FAX-only fix** that enables ServiceOps to correctly parse blob paths containing container names (e.g., `integration-inbound-fax/...`) from FAX payloads.

## Changes Included (FAX Fix Only)

### File Modified
- **File**: `wiser-service-operations-backend/app/services/payload_parser.py`
- **Lines Changed**: 
  - Lines 313-340: New method `_extract_container_from_blob_path()`
  - Lines 392-403: Updated `_construct_source_absolute_url()` to use container extraction

### What the Fix Does

1. **Container Extraction Method** (`_extract_container_from_blob_path`)
   - Extracts container name from blob path if it starts with known containers
   - Known containers: `integration-inbound-fax`, `esmd-download`
   - Returns `(container_name, remaining_path)` if found, `None` otherwise

2. **URL Construction Update** (`_construct_source_absolute_url`)
   - Checks if blobPath contains container name prefix
   - If found, uses extracted container instead of environment variable
   - Falls back to environment variable if container not in path (backward compatible)

### Backward Compatibility
✅ **Fully backward compatible**
- Old format payloads (without container in path) still work
- Falls back to `AZURE_STORAGE_SOURCE_CONTAINER` env var if container not detected
- No breaking changes

## Files NOT Modified (Excluded from This Deployment)

The following features are **NOT** included in this FAX-only deployment:

- ❌ JSON Generator integration (`clinical_ops_inbox_processor.py`)
- ❌ Manual completion service (`manual_completion_service.py`)
- ❌ Dismissal workflow changes (`dismissal_workflow_service.py`)
- ❌ Extracted fields priority fix (JSON Generator repo)
- ❌ UI changes (frontend)
- ❌ Database migrations
- ❌ Any other service files

## Testing Checklist

Before deploying, verify:

- [x] Only `payload_parser.py` is modified
- [ ] FAX payload with `blobPath: "integration-inbound-fax/2026/01-15/.../file.pdf"` works correctly
- [ ] FAX payload with `blobPath: "2026/01-15/.../file.pdf"` (no container) still works (uses env var)
- [ ] Old format payloads (no `blobPath`) still work
- [ ] ESMD payload with `blobPath: "esmd-download/..."` works correctly
- [ ] Portal payloads (no container in path) still work

## Deployment Steps

1. **Verify Changes**
   ```bash
   # Check that only payload_parser.py is modified
   git status
   git diff app/services/payload_parser.py
   ```

2. **Test Locally**
   - Test with FAX payload containing container in blobPath
   - Test with old format payloads
   - Verify backward compatibility

3. **Deploy to Production**
   - Deploy only `payload_parser.py` changes
   - Monitor logs for container extraction messages
   - Verify FAX channel processing works correctly

## Risk Assessment

**Risk Level**: ✅ **LOW**

- Isolated to one file
- Backward compatible
- No database changes
- No breaking changes
- Self-contained logic
- Easy to rollback if needed

## Rollback Plan

If issues occur:
1. Revert `payload_parser.py` to previous version
2. System will fall back to using environment variable for container name
3. No data migration needed

## Success Criteria

✅ FAX channel can process payloads with container names in blobPath
✅ Old format payloads continue to work
✅ No errors in production logs
✅ FAX documents are successfully downloaded from correct container

---

**Date**: 2026-01-15
**Deployment Type**: FAX Fix Only (Isolated)
**Files Changed**: 1 file (`payload_parser.py`)



