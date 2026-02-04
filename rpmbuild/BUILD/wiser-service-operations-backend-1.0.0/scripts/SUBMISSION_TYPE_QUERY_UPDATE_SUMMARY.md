# Submission Type Query Update Summary

## Problem

The original Query 6.2 used **exact matching** (`IN ('expedited', 'expedite', 'urgent', 'rush')`) which **does not work** for values with suffixes like:
- `'expedited-initial'` ❌ (won't match)
- `'standard-initial'` ❌ (won't match)
- `'expedited-someother'` ❌ (won't match)

## Solution

Updated queries now use **partial matching** (`LIKE 'expedited%'`) which matches values that **start with** the keyword:
- `'expedited-initial'` ✅ (matches `LIKE 'expedited%'`)
- `'standard-initial'` ✅ (matches `LIKE 'standard%'`)
- `'expedited-someother'` ✅ (matches `LIKE 'expedited%'`)

This matches the code logic that was just updated to use `startswith()` for submission type normalization.

---

## Files Created

### 1. `query_6.2_verify_due_date_UPDATED.sql`
**Simple, direct replacement** for the original Query 6.2.

**Changes:**
- Replaced `LOWER(TRIM(submission_type)) IN ('expedited', 'expedite', 'urgent', 'rush')` 
- With: `LOWER(TRIM(submission_type)) LIKE 'expedited%' OR LIKE 'expedite%' OR LIKE 'urgent%' OR LIKE 'rush%'`
- Same for standard keywords

**Usage:** Give this to the DBA as a direct replacement for Query 6.2.

---

### 2. `verify_due_date_calculations_updated.sql`
**Comprehensive verification and update script** with:
- Updated verification query (Query 6.2)
- Example query showing submission_type values that need updating
- Preview query (STEP 1)
- Update query (STEP 2) - commented out for safety
- Verification query (STEP 3)

**Usage:** For comprehensive verification and batch updates.

---

### 3. `UPDATE_submission_type_normalize.sql`
**Standalone update script** to normalize old records:
- STEP 1: Preview what will be updated
- STEP 2: Update query (commented out for safety)
- STEP 3: Instructions to verify

**Usage:** For normalizing existing records in the database.

---

## Key Changes in SQL

### Before (Exact Matching - BROKEN):
```sql
LOWER(TRIM(submission_type)) IN ('expedited', 'expedite', 'urgent', 'rush')
```

### After (Partial Matching - FIXED):
```sql
LOWER(TRIM(submission_type)) LIKE 'expedited%'
OR LOWER(TRIM(submission_type)) LIKE 'expedite%'
OR LOWER(TRIM(submission_type)) LIKE 'urgent%'
OR LOWER(TRIM(submission_type)) LIKE 'rush%'
```

---

## Expedited Keywords (Partial Match)
- `expedited%` - matches: 'expedited', 'expedited-initial', 'expedited-someother', etc.
- `expedite%` - matches: 'expedite', 'expedite-review', etc.
- `urgent%` - matches: 'urgent', 'urgent-review', etc.
- `rush%` - matches: 'rush', 'rush-processing', etc.

## Standard Keywords (Partial Match)
- `standard%` - matches: 'standard', 'standard-initial', 'standard-some other value', etc.
- `normal%` - matches: 'normal', 'normal-routine', etc.
- `routine%` - matches: 'routine', 'routine-check', etc.
- `regular%` - matches: 'regular', 'regular-review', etc.

---

## Testing

The updated queries will now correctly:
1. ✅ Identify `'expedited-initial'` as Expedited (48 hours)
2. ✅ Identify `'standard-initial'` as Standard (72 hours)
3. ✅ Verify due_date calculations for these values
4. ✅ Update old records to normalized values

---

## Next Steps for DBA

1. **Run the updated Query 6.2** (`query_6.2_verify_due_date_UPDATED.sql`) to verify current state
2. **Review the preview** from `UPDATE_submission_type_normalize.sql` (STEP 1)
3. **If preview looks correct**, uncomment and run the UPDATE query (STEP 2)
4. **Verify** by running Query 6.2 again

---

## Code Alignment

The SQL queries now match the Python code logic:
- **Python:** `value_lower.startswith('expedited')`
- **SQL:** `LOWER(TRIM(submission_type)) LIKE 'expedited%'`

Both use partial matching (starts with) to handle values with suffixes.

