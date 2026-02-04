"""
Backfill packet table with OCR-extracted values for existing packets
This script updates packet.beneficiary_name, beneficiary_mbi, provider_name, provider_npi
from packet_document.extracted_fields for packets that still have TBD values
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import get_db_session
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.utils.packet_converter import extract_from_ocr_fields
from datetime import datetime, timezone


def backfill_packet_from_ocr(packet_external_id: str, dry_run: bool = True):
    """
    Backfill packet table with OCR values from packet_document.extracted_fields
    
    Args:
        packet_external_id: External ID of the packet (e.g., "PKT-2026-503899")
        dry_run: If True, only show what would be updated without making changes
    """
    print("=" * 80)
    print(f"BACKFILLING PACKET TABLE FROM OCR: {packet_external_id}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will update database)'}")
    print("=" * 80)
    
    with get_db_session() as db:
        # Get packet
        packet = db.query(PacketDB).filter(
            PacketDB.external_id == packet_external_id
        ).first()
        
        if not packet:
            print(f"[ERROR] Packet {packet_external_id} not found")
            return False
        
        print(f"\n[INFO] Found packet: packet_id={packet.packet_id}")
        print(f"  Current values:")
        print(f"    beneficiary_name: {packet.beneficiary_name}")
        print(f"    beneficiary_mbi: {packet.beneficiary_mbi}")
        print(f"    provider_name: {packet.provider_name}")
        print(f"    provider_npi: {packet.provider_npi}")
        
        # Get consolidated document
        document = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if not document:
            print(f"\n[ERROR] No document found for packet {packet_external_id}")
            return False
        
        print(f"\n[INFO] Found document: packet_document_id={document.packet_document_id}")
        print(f"  OCR status: {document.ocr_status}")
        
        if not document.extracted_fields or not document.extracted_fields.get('fields'):
            print(f"\n[ERROR] No extracted_fields found in document")
            return False
        
        fields = document.extracted_fields['fields']
        print(f"  Extracted fields count: {len(fields)}")
        
        # Extract beneficiary info from OCR
        beneficiary_last_name = extract_from_ocr_fields(
            [document], 
            [
                'Beneficiary Last Name', 'beneficiaryLastName', 'beneficiary_last_name',
                'Patient Last Name', 'patientLastName', 'patient_last_name',
                'Member Last Name', 'memberLastName', 'member_last_name',
                'Last Name', 'lastName', 'last_name', 'lname'
            ]
        )
        beneficiary_first_name = extract_from_ocr_fields(
            [document],
            [
                'Beneficiary First Name', 'beneficiaryFirstName', 'beneficiary_first_name',
                'Patient First Name', 'patientFirstName', 'patient_first_name',
                'Member First Name', 'memberFirstName', 'member_first_name',
                'First Name', 'firstName', 'first_name', 'fname'
            ]
        )
        if beneficiary_first_name and beneficiary_last_name:
            ocr_beneficiary_name = f"{beneficiary_first_name} {beneficiary_last_name}".strip()
        else:
            ocr_beneficiary_name = extract_from_ocr_fields(
                [document],
                [
                    'Beneficiary Name', 'beneficiaryName', 'beneficiary_name',
                    'Patient Name', 'patientName', 'patient_name',
                    'Member Name', 'memberName', 'member_name',
                    'Full Name', 'fullName', 'full_name'
                ]
            )
        
        ocr_beneficiary_mbi = extract_from_ocr_fields(
            [document],
            [
                'Beneficiary Medicare ID',
                'Medicare ID', 'medicareId', 'MBI', 'mbi', 'Beneficiary MBI', 'beneficiaryMbi',
                'Medicare Beneficiary Identifier', 'Medicare Number', 'medicareNumber',
                'HICN', 'hicn', 'Health Insurance Claim Number'
            ]
        )
        
        # Extract provider info from OCR
        facility_name = extract_from_ocr_fields(
            [document],
            [
                'Facility Provider Name',
                'Facility Name', 'facilityName', 'facility_name',
                'Organization Name', 'organizationName', 'organization_name',
                'Practice Name', 'practiceName', 'practice_name'
            ]
        )
        physician_name = extract_from_ocr_fields(
            [document],
            [
                'Attending Physician Name',
                'Physician Name', 'physicianName', 'physician_name',
                'Ordering/Referring Physician Name', 'Ordering Physician Name',
                'Referring Physician Name', 'Doctor Name', 'doctorName',
                'Attending Physician', 'attendingPhysician'
            ]
        )
        ocr_provider_name = facility_name or physician_name or extract_from_ocr_fields(
            [document],
            [
                'Provider Name', 'providerName', 'provider_name',
                'Rendering Provider Name', 'renderingProviderName',
                'Billing Provider Name', 'billingProviderName'
            ]
        )
        
        facility_npi = extract_from_ocr_fields(
            [document],
            [
                'Facility Provider NPI',
                'Facility NPI', 'facilityNpi', 'facility_npi',
                'Organization NPI', 'organizationNpi', 'organization_npi'
            ]
        )
        physician_npi = extract_from_ocr_fields(
            [document],
            [
                'Attending Physician NPI',
                'Physician NPI', 'physicianNpi', 'physician_npi',
                'Ordering/Referring Physician NPI', 'Ordering Physician NPI',
                'Referring Physician NPI', 'Doctor NPI', 'doctorNpi'
            ]
        )
        # Prefer Attending Physician NPI (usually 10 digits) over Facility Provider NPI (may be 9 digits)
        ocr_provider_npi = physician_npi or facility_npi or extract_from_ocr_fields(
            [document],
            [
                'Provider NPI', 'providerNpi', 'provider_npi',
                'Rendering Provider NPI', 'renderingProviderNpi',
                'Billing Provider NPI', 'billingProviderNpi',
                'NPI', 'npi'
            ]
        )
        
        print(f"\n[INFO] OCR extracted values:")
        print(f"    beneficiary_name: {ocr_beneficiary_name or 'NOT FOUND'}")
        print(f"    beneficiary_mbi: {ocr_beneficiary_mbi or 'NOT FOUND'}")
        print(f"    provider_name: {ocr_provider_name or 'NOT FOUND'}")
        print(f"    provider_npi: {ocr_provider_npi or 'NOT FOUND'}")
        
        # Determine what needs to be updated
        updates = {}
        
        if ocr_beneficiary_name and (not packet.beneficiary_name or packet.beneficiary_name == "TBD"):
            updates['beneficiary_name'] = ocr_beneficiary_name
        
        if ocr_beneficiary_mbi and (not packet.beneficiary_mbi or packet.beneficiary_mbi == "TBD"):
            updates['beneficiary_mbi'] = ocr_beneficiary_mbi
        
        if ocr_provider_name and (not packet.provider_name or packet.provider_name == "TBD"):
            updates['provider_name'] = ocr_provider_name
        
        # Normalize provider_npi
        if ocr_provider_npi:
            npi_clean = ''.join(c for c in str(ocr_provider_npi) if c.isdigit())
            if len(npi_clean) == 10:
                if not packet.provider_npi or packet.provider_npi == "TBD" or packet.provider_npi == "0000000000":
                    updates['provider_npi'] = npi_clean
            elif len(npi_clean) == 9:
                # Pad 9-digit NPI with leading zero
                npi_clean = '0' + npi_clean
                if not packet.provider_npi or packet.provider_npi == "TBD" or packet.provider_npi == "0000000000":
                    updates['provider_npi'] = npi_clean
                print(f"  [INFO] Will pad 9-digit NPI: {ocr_provider_npi} -> {npi_clean}")
            else:
                print(f"  [WARN] Invalid NPI: {ocr_provider_npi} (not 10 digits, got {len(npi_clean)})")
        elif not packet.provider_npi or packet.provider_npi == "TBD":
            updates['provider_npi'] = "0000000000"
        
        if not updates:
            print(f"\n[INFO] No updates needed - packet table already has non-TBD values")
            return True
        
        print(f"\n[INFO] Will update {len(updates)} field(s):")
        for field, value in updates.items():
            print(f"    {field}: {packet.__dict__[field]} -> {value}")
        
        if dry_run:
            print(f"\n[DRY RUN] Would update packet table (use --live to apply changes)")
            return True
        
        # Apply updates
        try:
            for field, value in updates.items():
                setattr(packet, field, value)
            packet.updated_at = datetime.now(timezone.utc)
            
            db.commit()
            db.refresh(packet)
            
            print(f"\n[SUCCESS] Updated packet {packet_external_id} with OCR values")
            print(f"  New values:")
            print(f"    beneficiary_name: {packet.beneficiary_name}")
            print(f"    beneficiary_mbi: {packet.beneficiary_mbi}")
            print(f"    provider_name: {packet.provider_name}")
            print(f"    provider_npi: {packet.provider_npi}")
            
            return True
        except Exception as e:
            db.rollback()
            print(f"\n[ERROR] Failed to update packet: {e}")
            import traceback
            traceback.print_exc()
            return False


def backfill_all_packets_with_tbd(dry_run: bool = True):
    """
    Backfill all packets that have TBD values but have OCR data available
    """
    print("=" * 80)
    print(f"BACKFILLING ALL PACKETS WITH TBD VALUES")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will update database)'}")
    print("=" * 80)
    
    with get_db_session() as db:
        # Find packets with TBD values that have documents with extracted_fields
        packets = db.query(PacketDB).join(
            PacketDocumentDB, PacketDB.packet_id == PacketDocumentDB.packet_id
        ).filter(
            (PacketDB.beneficiary_name == "TBD") | 
            (PacketDB.provider_name == "TBD") |
            (PacketDB.provider_npi == "TBD")
        ).filter(
            PacketDocumentDB.extracted_fields.isnot(None)
        ).all()
        
        print(f"\n[INFO] Found {len(packets)} packet(s) with TBD values and OCR data")
        
        if not packets:
            print("[INFO] No packets need backfilling")
            return
        
        success_count = 0
        for packet in packets:
            print(f"\n{'='*80}")
            result = backfill_packet_from_ocr(packet.external_id, dry_run=dry_run)
            if result:
                success_count += 1
        
        print(f"\n{'='*80}")
        print(f"[SUMMARY] Processed {len(packets)} packet(s), {success_count} successful")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill packet table from OCR data')
    parser.add_argument('packet_id', nargs='?', help='Packet external ID (e.g., PKT-2026-503899). If not provided, backfills all packets with TBD values')
    parser.add_argument('--live', action='store_true', help='Actually update the database (default is dry run)')
    parser.add_argument('--all', action='store_true', help='Backfill all packets with TBD values')
    
    args = parser.parse_args()
    
    dry_run = not args.live
    
    if args.all:
        backfill_all_packets_with_tbd(dry_run=dry_run)
    elif args.packet_id:
        success = backfill_packet_from_ocr(args.packet_id, dry_run=dry_run)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
        sys.exit(1)

