#!/usr/bin/env python3
"""
Script to check the "Diagnosis codes" field value in the database
before and after manual updates.
"""
import sys
import os
import json
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import get_db_session
from app.models.document_db import PacketDocumentDB

def check_diagnosis_code_value(external_id: str = 'DOC-3835'):
    """Check the Diagnosis codes field value in the database."""
    db = next(get_db_session())
    
    try:
        doc = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.external_id == external_id
        ).first()
        
        if not doc:
            print(f"❌ Document {external_id} not found")
            return
        
        print(f"\n{'='*80}")
        print(f"📄 Document: {doc.external_id} (Packet: {doc.packet_id})")
        print(f"{'='*80}\n")
        
        # Check extracted_fields
        print("🔍 EXTRACTED_FIELDS (working view):")
        print("-" * 80)
        if doc.extracted_fields:
            fields = doc.extracted_fields.get('fields', {})
            diagnosis_field = fields.get('Diagnosis codes')
            
            if diagnosis_field:
                print(f"  ✓ Field 'Diagnosis codes' found")
                print(f"    Value: {repr(diagnosis_field.get('value', 'NOT FOUND'))}")
                print(f"    Source: {diagnosis_field.get('source', 'N/A')}")
                print(f"    Confidence: {diagnosis_field.get('confidence', 'N/A')}")
                print(f"    Full field data: {json.dumps(diagnosis_field, indent=6)}")
            else:
                print(f"  ❌ Field 'Diagnosis codes' NOT FOUND in fields")
                print(f"    Available fields: {list(fields.keys())[:10]}...")
            
            # Also check raw fields
            raw_fields = doc.extracted_fields.get('raw', {}).get('fields', {})
            raw_diagnosis = raw_fields.get('Diagnosis codes')
            if raw_diagnosis:
                print(f"\n  📋 RAW (preserved OCR):")
                print(f"    Value: {repr(raw_diagnosis.get('value', 'NOT FOUND') if isinstance(raw_diagnosis, dict) else raw_diagnosis)}")
        else:
            print("  ❌ extracted_fields is NULL")
        
        # Check updated_extracted_fields
        print(f"\n🔍 UPDATED_EXTRACTED_FIELDS (manual review snapshot):")
        print("-" * 80)
        if doc.updated_extracted_fields:
            updated_fields = doc.updated_extracted_fields.get('fields', {})
            updated_diagnosis = updated_fields.get('Diagnosis codes')
            
            if updated_diagnosis:
                print(f"  ✓ Field 'Diagnosis codes' found")
                print(f"    Value: {repr(updated_diagnosis.get('value', 'NOT FOUND'))}")
                print(f"    Source: {updated_diagnosis.get('source', 'N/A')}")
                print(f"    Last updated: {doc.updated_extracted_fields.get('last_updated_at', 'N/A')}")
                print(f"    Last updated by: {doc.updated_extracted_fields.get('last_updated_by', 'N/A')}")
            else:
                print(f"  ❌ Field 'Diagnosis codes' NOT FOUND in updated_extracted_fields")
        else:
            print("  ❌ updated_extracted_fields is NULL")
        
        # Check extracted_fields_update_history
        print(f"\n🔍 EXTRACTED_FIELDS_UPDATE_HISTORY (audit trail):")
        print("-" * 80)
        if doc.extracted_fields_update_history:
            print(f"  ✓ History has {len(doc.extracted_fields_update_history)} entry/entries")
            for i, entry in enumerate(doc.extracted_fields_update_history, 1):
                print(f"\n  Entry {i}:")
                print(f"    Updated at: {entry.get('updated_at', 'N/A')}")
                print(f"    Updated by: {entry.get('updated_by', 'N/A')}")
                changed_fields = entry.get('changed_fields', {})
                if 'Diagnosis codes' in changed_fields:
                    change = changed_fields['Diagnosis codes']
                    print(f"    ✓ 'Diagnosis codes' changed:")
                    print(f"      Old: {repr(change.get('old', 'N/A'))}")
                    print(f"      New: {repr(change.get('new', 'N/A'))}")
                else:
                    print(f"    Changed fields: {list(changed_fields.keys())}")
        else:
            print("  ❌ extracted_fields_update_history is NULL or empty")
        
        print(f"\n{'='*80}\n")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == '__main__':
    doc_id = sys.argv[1] if len(sys.argv) > 1 else 'DOC-3835'
    check_diagnosis_code_value(doc_id)








