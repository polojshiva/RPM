"""Quick check of extracted_fields vs updated_extracted_fields structure"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import get_db
from app.models.document_db import PacketDocumentDB
import json

db = next(get_db())
doc = db.query(PacketDocumentDB).filter(PacketDocumentDB.external_id == 'DOC-2').first()

if not doc:
    print("DOC-2 not found")
    sys.exit(1)

ef = doc.extracted_fields
uef = doc.updated_extracted_fields

print("=" * 80)
print("STRUCTURE COMPARISON")
print("=" * 80)

print("\n1. EXTRACTED_FIELDS top-level keys:")
if ef:
    print(f"   {list(ef.keys())}")
    if 'fields' in ef:
        print(f"   fields count: {len(ef['fields'])}")
    if 'raw' in ef:
        print(f"   raw type: {type(ef['raw'])}")
        if isinstance(ef['raw'], dict):
            print(f"   raw keys: {list(ef['raw'].keys())[:5]}")
else:
    print("   NULL")

print("\n2. UPDATED_EXTRACTED_FIELDS top-level keys:")
if uef:
    print(f"   {list(uef.keys())}")
    if 'fields' in uef:
        print(f"   fields count: {len(uef['fields'])}")
    if 'raw' in uef:
        print(f"   raw type: {type(uef['raw'])}")
        if isinstance(uef['raw'], dict):
            print(f"   raw keys: {list(uef['raw'].keys())[:5]}")
else:
    print("   NULL")

print("\n3. DUPLICATE CHECK:")
if ef and uef and isinstance(ef, dict) and isinstance(uef, dict):
    # Check for duplicate keys in fields
    if 'fields' in ef and 'fields' in uef:
        ef_fields = ef['fields']
        uef_fields = uef['fields']
        
        # Check for case-insensitive duplicates
        from collections import Counter
        ef_lower = [k.lower() for k in ef_fields.keys()]
        uef_lower = [k.lower() for k in uef_fields.keys()]
        
        ef_dups = {k: v for k, v in Counter(ef_lower).items() if v > 1}
        uef_dups = {k: v for k, v in Counter(uef_lower).items() if v > 1}
        
        if ef_dups:
            print(f"   ⚠ Duplicates in extracted_fields.fields:")
            for dup, count in ef_dups.items():
                matches = [k for k in ef_fields.keys() if k.lower() == dup]
                print(f"      '{dup}': {matches}")
        else:
            print("   ✓ No duplicates in extracted_fields.fields")
            
        if uef_dups:
            print(f"   ⚠ Duplicates in updated_extracted_fields.fields:")
            for dup, count in uef_dups.items():
                matches = [k for k in uef_fields.keys() if k.lower() == dup]
                print(f"      '{dup}': {matches}")
        else:
            print("   ✓ No duplicates in updated_extracted_fields.fields")
    
    # Check if 'raw' is nested incorrectly
    if 'raw' in uef:
        uef_raw = uef['raw']
        if isinstance(uef_raw, dict):
            # Check if raw contains another 'raw' key (nested)
            if 'raw' in uef_raw:
                print(f"   ⚠ NESTED 'raw' found in updated_extracted_fields.raw!")
                print(f"      This suggests 'raw' was merged incorrectly")
            # Check if raw contains 'fields' (wrong structure)
            if 'fields' in uef_raw:
                print(f"   ⚠ 'fields' found inside 'raw' - wrong structure!")

print("\n4. SAMPLE FIELD STRUCTURE:")
if uef and 'fields' in uef and uef['fields']:
    sample_key = list(uef['fields'].keys())[0]
    sample_value = uef['fields'][sample_key]
    print(f"   Sample field '{sample_key}':")
    print(f"      Type: {type(sample_value)}")
    if isinstance(sample_value, dict):
        print(f"      Keys: {list(sample_value.keys())}")
        print(f"      Value: {sample_value.get('value', 'N/A')[:50]}")

print("\n" + "=" * 80)

