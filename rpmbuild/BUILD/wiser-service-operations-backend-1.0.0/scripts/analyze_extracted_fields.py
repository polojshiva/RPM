"""
Root Cause Analysis: Compare extracted_fields vs updated_extracted_fields
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import get_db
from app.models.document_db import PacketDocumentDB
import json
from collections import Counter

db = next(get_db())

# Get document
doc = db.query(PacketDocumentDB).filter(PacketDocumentDB.external_id == 'DOC-2').first()

if not doc:
    print("Document DOC-2 not found")
    sys.exit(1)

print("=" * 80)
print("ROOT CAUSE ANALYSIS: extracted_fields vs updated_extracted_fields")
print("=" * 80)

# Get both fields
ef = doc.extracted_fields
uef = doc.updated_extracted_fields

print("\n1. EXTRACTED_FIELDS STRUCTURE:")
print("-" * 80)
if ef:
    print(f"Type: {type(ef)}")
    print(f"Top-level keys: {list(ef.keys()) if isinstance(ef, dict) else 'N/A'}")
    if isinstance(ef, dict):
        if 'fields' in ef:
            print(f"  'fields' keys count: {len(ef['fields'])}")
            print(f"  'fields' sample keys: {list(ef['fields'].keys())[:5]}")
        if 'raw' in ef:
            print(f"  'raw' keys: {list(ef['raw'].keys()) if isinstance(ef['raw'], dict) else 'N/A'}")
    print(f"\nFull structure (first 2000 chars):")
    print(json.dumps(ef, indent=2)[:2000])
else:
    print("NULL")

print("\n2. UPDATED_EXTRACTED_FIELDS STRUCTURE:")
print("-" * 80)
if uef:
    print(f"Type: {type(uef)}")
    print(f"Top-level keys: {list(uef.keys()) if isinstance(uef, dict) else 'N/A'}")
    if isinstance(uef, dict):
        if 'fields' in uef:
            print(f"  'fields' keys count: {len(uef['fields'])}")
            print(f"  'fields' sample keys: {list(uef['fields'].keys())[:5]}")
        if 'raw' in uef:
            print(f"  'raw' keys: {list(uef['raw'].keys()) if isinstance(uef['raw'], dict) else 'N/A'}")
    print(f"\nFull structure (first 2000 chars):")
    print(json.dumps(uef, indent=2)[:2000])
else:
    print("NULL")

print("\n3. COMPARISON:")
print("-" * 80)

if ef and uef and isinstance(ef, dict) and isinstance(uef, dict):
    # Compare top-level structure
    ef_top_keys = set(ef.keys())
    uef_top_keys = set(uef.keys())
    print(f"Top-level keys in extracted_fields: {ef_top_keys}")
    print(f"Top-level keys in updated_extracted_fields: {uef_top_keys}")
    print(f"Missing in updated: {ef_top_keys - uef_top_keys}")
    print(f"Extra in updated: {uef_top_keys - ef_top_keys}")
    
    # Compare 'fields' structure
    if 'fields' in ef and 'fields' in uef:
        ef_fields = ef['fields']
        uef_fields = uef['fields']
        
        ef_field_names = set(ef_fields.keys())
        uef_field_names = set(uef_fields.keys())
        
        print(f"\nFields in extracted_fields: {len(ef_field_names)}")
        print(f"Fields in updated_extracted_fields: {len(uef_field_names)}")
        print(f"Fields only in extracted_fields: {ef_field_names - uef_field_names}")
        print(f"Fields only in updated_extracted_fields: {uef_field_names - ef_field_names}")
        print(f"Common fields: {len(ef_field_names & uef_field_names)}")
        
        # Check for duplicate field names (case-insensitive)
        ef_lower = {k.lower(): k for k in ef_fields.keys()}
        uef_lower = {k.lower(): k for k in uef_fields.keys()}
        
        print(f"\nCase-insensitive duplicates in extracted_fields:")
        ef_counter = Counter(k.lower() for k in ef_fields.keys())
        ef_dups = {k: v for k, v in ef_counter.items() if v > 1}
        if ef_dups:
            for lower_name, count in ef_dups.items():
                matches = [k for k in ef_fields.keys() if k.lower() == lower_name]
                print(f"  '{lower_name}' appears {count} times: {matches}")
        else:
            print("  None")
        
        print(f"\nCase-insensitive duplicates in updated_extracted_fields:")
        uef_counter = Counter(k.lower() for k in uef_fields.keys())
        uef_dups = {k: v for k, v in uef_counter.items() if v > 1}
        if uef_dups:
            for lower_name, count in uef_dups.items():
                matches = [k for k in uef_fields.keys() if k.lower() == lower_name]
                print(f"  '{lower_name}' appears {count} times: {matches}")
        else:
            print("  None")
        
        # Compare field value structure
        print(f"\nField value structure comparison:")
        sample_field = list(ef_field_names & uef_field_names)[0] if (ef_field_names & uef_field_names) else None
        if sample_field:
            ef_value = ef_fields[sample_field]
            uef_value = uef_fields.get(sample_field)
            print(f"Sample field '{sample_field}':")
            print(f"  extracted_fields value type: {type(ef_value)}")
            print(f"  updated_extracted_fields value type: {type(uef_value)}")
            if isinstance(ef_value, dict):
                print(f"  extracted_fields value keys: {list(ef_value.keys())}")
            if isinstance(uef_value, dict):
                print(f"  updated_extracted_fields value keys: {list(uef_value.keys())}")
    
    # Compare 'raw' structure
    if 'raw' in ef and 'raw' in uef:
        print(f"\n'raw' structure comparison:")
        ef_raw = ef['raw']
        uef_raw = uef['raw']
        print(f"  extracted_fields.raw type: {type(ef_raw)}")
        print(f"  updated_extracted_fields.raw type: {type(uef_raw)}")
        if isinstance(ef_raw, dict) and isinstance(uef_raw, dict):
            print(f"  extracted_fields.raw keys: {list(ef_raw.keys())}")
            print(f"  updated_extracted_fields.raw keys: {list(uef_raw.keys())}")

print("\n4. ROOT CAUSE ANALYSIS:")
print("-" * 80)
print("Checking update_extracted_fields endpoint logic...")

# Check if there's a structure mismatch issue
if ef and uef:
    # Check if 'raw' is being duplicated
    if 'raw' in ef and 'raw' in uef:
        ef_raw_str = json.dumps(ef['raw'], sort_keys=True)
        uef_raw_str = json.dumps(uef['raw'], sort_keys=True)
        if ef_raw_str == uef_raw_str:
            print("✓ 'raw' structure is identical (expected)")
        else:
            print("⚠ 'raw' structure differs (potential issue)")
    
    # Check if fields structure is nested differently
    if 'fields' in ef and 'fields' in uef:
        # Check if there's nesting issue
        ef_sample = list(ef['fields'].values())[0] if ef['fields'] else None
        uef_sample = list(uef['fields'].values())[0] if uef['fields'] else None
        
        if isinstance(ef_sample, dict) and isinstance(uef_sample, dict):
            ef_sample_keys = set(ef_sample.keys())
            uef_sample_keys = set(uef_sample.keys())
            if ef_sample_keys != uef_sample_keys:
                print(f"⚠ Field value structure differs:")
                print(f"  extracted_fields field structure: {ef_sample_keys}")
                print(f"  updated_extracted_fields field structure: {uef_sample_keys}")

print("\n" + "=" * 80)
print("Analysis complete")

