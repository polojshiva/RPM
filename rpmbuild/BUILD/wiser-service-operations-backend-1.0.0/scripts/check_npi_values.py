import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine

def check_npi_values():
    """Check if any documents have actual NPI values (not empty)."""
    print("=" * 80)
    print("CHECKING FOR DOCUMENTS WITH NPI VALUES")
    print("=" * 80)
    
    try:
        with engine.connect() as conn:
            # Get documents with NPI fields
            result = conn.execute(text("""
                SELECT 
                    packet_document_id,
                    external_id,
                    extracted_fields->'fields'->'Attending Physician NPI'->>'value' as physician_npi,
                    extracted_fields->'fields'->'Facility Provider NPI'->>'value' as facility_npi
                FROM service_ops.packet_document
                WHERE extracted_fields IS NOT NULL
                ORDER BY packet_document_id DESC
                LIMIT 10
            """))
            
            rows = result.fetchall()
            
            if not rows:
                print("No documents found.")
                return
            
            print(f"\nFound {len(rows)} documents:\n")
            found_with_values = False
            
            for row in rows:
                doc_id, external_id, physician_npi, facility_npi = row
                physician_npi = physician_npi.strip() if physician_npi else None
                facility_npi = facility_npi.strip() if facility_npi else None
                
                if physician_npi or facility_npi:
                    found_with_values = True
                    print(f"Document: {external_id} (ID: {doc_id})")
                    if physician_npi:
                        print(f"  Attending Physician NPI: {physician_npi}")
                    if facility_npi:
                        print(f"  Facility Provider NPI: {facility_npi}")
                    print()
            
            if not found_with_values:
                print("No documents found with non-empty NPI values.")
                print("All NPI fields are empty or null.")
                print("\nThis could mean:")
                print("  1. OCR did not extract NPI values from the documents")
                print("  2. The documents don't contain NPI information")
                print("  3. The NPI fields need to be manually entered")
            
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    check_npi_values()






