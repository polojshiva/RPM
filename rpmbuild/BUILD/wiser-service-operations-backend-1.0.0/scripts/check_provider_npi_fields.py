import sys
from pathlib import Path
import json
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine

def check_provider_npi_fields():
    """Check what NPI-related fields are actually stored in extracted_fields."""
    print("=" * 80)
    print("CHECKING PROVIDER NPI FIELDS IN DATABASE")
    print("=" * 80)
    
    try:
        with engine.connect() as conn:
            # Get the most recent document with extracted_fields
            result = conn.execute(text("""
                SELECT 
                    packet_document_id,
                    external_id,
                    extracted_fields->'fields' as fields
                FROM service_ops.packet_document
                WHERE extracted_fields IS NOT NULL
                ORDER BY packet_document_id DESC
                LIMIT 1
            """))
            
            row = result.fetchone()
            
            if not row:
                print("No documents with extracted_fields found.")
                return
            
            doc_id, external_id, fields = row
            print(f"\nDocument: {external_id} (ID: {doc_id})")
            
            if not fields or not isinstance(fields, dict):
                print("No fields found in extracted_fields.")
                return
            
            # Find all NPI-related fields
            npi_fields = {}
            for key, value in fields.items():
                if 'npi' in key.lower():
                    npi_fields[key] = value
            
            print("\n" + "=" * 80)
            print("NPI-RELATED FIELDS FOUND:")
            print("=" * 80)
            if npi_fields:
                for key, value in npi_fields.items():
                    if isinstance(value, dict):
                        print(f"  {key}: {value.get('value', 'N/A')} (confidence: {value.get('confidence', 'N/A')})")
                    else:
                        print(f"  {key}: {value}")
            else:
                print("  No NPI-related fields found!")
            
            print("\n" + "=" * 80)
            print("ALL FIELD NAMES (first 30):")
            print("=" * 80)
            all_keys = list(fields.keys())
            for i, key in enumerate(all_keys[:30], 1):
                print(f"  {i}. {key}")
            if len(all_keys) > 30:
                print(f"  ... and {len(all_keys) - 30} more fields")
            
            # Check specifically for the fields the frontend is looking for
            print("\n" + "=" * 80)
            print("CHECKING FRONTEND FIELD NAMES:")
            print("=" * 80)
            frontend_field_names = [
                'Provider NPI',
                'providerNpi',
                'provider_npi',
                'NPI',
                'npi',
                'Attending Physician NPI',
                'Facility Provider NPI',
                'Physician NPI',
                'Facility NPI'
            ]
            
            for field_name in frontend_field_names:
                if field_name in fields:
                    value = fields[field_name]
                    if isinstance(value, dict):
                        print(f"  FOUND '{field_name}': {value.get('value', 'N/A')}")
                    else:
                        print(f"  FOUND '{field_name}': {value}")
                else:
                    # Try case-insensitive
                    matching_key = next((k for k in fields.keys() if k.lower() == field_name.lower()), None)
                    if matching_key:
                        value = fields[matching_key]
                        if isinstance(value, dict):
                            print(f"  ~ '{field_name}' (found as '{matching_key}'): {value.get('value', 'N/A')}")
                        else:
                            print(f"  ~ '{field_name}' (found as '{matching_key}'): {value}")
                    else:
                        print(f"  X '{field_name}': NOT FOUND")
            
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    check_provider_npi_fields()

