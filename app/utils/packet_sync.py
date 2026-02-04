"""
Packet synchronization utility
Syncs packet table columns from extracted_fields/updated_extracted_fields
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from app.models.packet_db import PacketDB

logger = logging.getLogger(__name__)


def sync_packet_from_extracted_fields(
    packet: PacketDB,
    extracted_fields_dict: Dict[str, Any],
    now: datetime,
    db: Any  # Session type, but avoiding circular import
) -> bool:
    """
    Shared helper to sync packet table fields from document extracted_fields.
    
    Updates packet table for mapped fields:
    - Beneficiary Name (from first+last or direct name fields)
    - Beneficiary MBI
    - Provider Name
    - Provider NPI (normalized to 10 digits)
    - Provider Fax
    - HCPCS (concatenated from Procedure Code set 1/2/3)
    - procedure_code_1, procedure_code_2, procedure_code_3 (individual codes)
    - submission_type (normalized)
    
    Args:
        packet: PacketDB instance to update
        extracted_fields_dict: Dictionary with 'fields' key containing field data
        now: Current datetime for timestamp updates
        db: Database session (for potential future use)
    
    Returns:
        bool: True if packet was updated, False otherwise
    """
    packet_updated = False
    packet_external_id = getattr(packet, 'external_id', 'unknown')
    
    # Log initial state
    logger.info(
        f"[sync_packet] Starting sync for packet {packet_external_id}. "
        f"Current values: beneficiary_name='{packet.beneficiary_name}', "
        f"beneficiary_mbi='{packet.beneficiary_mbi}', "
        f"provider_name='{packet.provider_name}', "
        f"provider_npi='{packet.provider_npi}'"
    )
    
    # Get fields dict
    if not extracted_fields_dict:
        logger.warning(
            f"[sync_packet] extracted_fields_dict is None or empty for packet {packet_external_id}. "
            f"Cannot sync packet fields."
        )
        return False
    
    if not isinstance(extracted_fields_dict, dict):
        logger.error(
            f"[sync_packet] extracted_fields_dict is not a dict for packet {packet_external_id}. "
            f"Type: {type(extracted_fields_dict)}. Cannot sync packet fields."
        )
        return False
    
    fields = extracted_fields_dict.get('fields', {})
    
    if not fields:
        logger.warning(
            f"[sync_packet] No 'fields' key or fields dict is empty in extracted_fields_dict for packet {packet_external_id}. "
            f"Structure: {list(extracted_fields_dict.keys()) if isinstance(extracted_fields_dict, dict) else 'N/A'}. "
            f"Cannot sync packet fields."
        )
        return False
    
    # Log available fields
    logger.info(
        f"[sync_packet] Available fields in extracted_fields_dict: {list(fields.keys())[:10]}... "
        f"(total: {len(fields)})"
    )
    
    # Helper to get field value from fields dict
    def get_field_value(field_names: list) -> Optional[str]:
        for field_name in field_names:
            if field_name in fields:
                field_data = fields[field_name]
                if isinstance(field_data, dict):
                    value = str(field_data.get('value', '')).strip()
                else:
                    value = str(field_data).strip()
                if value and value not in ['TBD', 'N/A', '']:
                    return value
        return None
    
    # Beneficiary Name: try first+last, then direct name fields
    beneficiary_first = get_field_value(['Beneficiary First Name', 'Patient First Name', 'First Name'])
    beneficiary_last = get_field_value(['Beneficiary Last Name', 'Patient Last Name', 'Last Name'])
    beneficiary_name = get_field_value(['Beneficiary Name', 'Patient Name', 'Member Name', 'Beneficiary Full Name'])
    
    logger.debug(
        f"[sync_packet] Beneficiary name extraction: first='{beneficiary_first}', "
        f"last='{beneficiary_last}', full='{beneficiary_name}'"
    )
    
    if beneficiary_first and beneficiary_last:
        combined_name = f"{beneficiary_first} {beneficiary_last}".strip()
        # Check if current value is None, empty, or TBD (case-insensitive)
        current_name = packet.beneficiary_name or ""
        is_tbd_or_empty = not current_name or current_name.upper() == "TBD"
        if is_tbd_or_empty or combined_name != packet.beneficiary_name:
            old_value = packet.beneficiary_name
            packet.beneficiary_name = combined_name
            packet_updated = True
            logger.info(
                f"[sync_packet] Updated beneficiary_name: '{old_value}' -> '{combined_name}' "
                f"(from first+last names)"
            )
    elif beneficiary_name:
        # Check if current value is None, empty, or TBD (case-insensitive)
        current_name = packet.beneficiary_name or ""
        is_tbd_or_empty = not current_name or current_name.upper() == "TBD"
        if is_tbd_or_empty:
            old_value = packet.beneficiary_name
            packet.beneficiary_name = beneficiary_name
            packet_updated = True
            logger.info(
                f"[sync_packet] Updated beneficiary_name: '{old_value}' -> '{beneficiary_name}' "
                f"(from full name field)"
            )
    
    # Beneficiary MBI
    beneficiary_mbi = get_field_value(['Beneficiary Medicare ID', 'Medicare ID', 'MBI', 'Beneficiary MBI', 'Medicare Beneficiary Identifier', 'HICN'])
    logger.debug(f"[sync_packet] Beneficiary MBI extraction: '{beneficiary_mbi}'")
    if beneficiary_mbi:
        # Check if current value is None, empty, or TBD (case-insensitive)
        current_mbi = packet.beneficiary_mbi or ""
        is_tbd_or_empty = not current_mbi or current_mbi.upper() == "TBD"
        if is_tbd_or_empty:
            old_value = packet.beneficiary_mbi
            packet.beneficiary_mbi = beneficiary_mbi
            packet_updated = True
            logger.info(f"[sync_packet] Updated beneficiary_mbi: '{old_value}' -> '{beneficiary_mbi}'")
    
    # Provider Name
    provider_name = get_field_value(['Facility Provider Name', 'Attending Physician Name', 'Provider Name', 'Rendering Provider Name', 'Billing Provider Name'])
    logger.debug(f"[sync_packet] Provider name extraction: '{provider_name}'")
    if provider_name:
        # Check if current value is None, empty, or TBD (case-insensitive)
        current_provider = packet.provider_name or ""
        is_tbd_or_empty = not current_provider or current_provider.upper() == "TBD"
        if is_tbd_or_empty:
            old_value = packet.provider_name
            packet.provider_name = provider_name
            packet_updated = True
            logger.info(f"[sync_packet] Updated provider_name: '{old_value}' -> '{provider_name}'")
    
    # Provider NPI (normalize to 10 digits)
    provider_npi = get_field_value(['Attending Physician NPI', 'Facility Provider NPI', 'Provider NPI', 'Rendering Provider NPI', 'Billing Provider NPI', 'NPI'])
    logger.debug(f"[sync_packet] Provider NPI extraction: '{provider_npi}'")
    if provider_npi:
        # Normalize: remove non-digits, pad 9 digits with leading zero
        npi_clean = ''.join(c for c in str(provider_npi) if c.isdigit())
        if len(npi_clean) == 9:
            npi_clean = '0' + npi_clean
        elif len(npi_clean) != 10:
            npi_clean = '0000000000'
        
        logger.debug(f"[sync_packet] Provider NPI normalized: '{provider_npi}' -> '{npi_clean}'")
        # Check if current value is None, empty, TBD (case-insensitive), or invalid
        current_npi = packet.provider_npi or ""
        is_tbd_or_empty_or_invalid = not current_npi or current_npi.upper() == "TBD" or current_npi == "0000000000"
        if is_tbd_or_empty_or_invalid:
            old_value = packet.provider_npi
            packet.provider_npi = npi_clean
            packet_updated = True
            logger.info(f"[sync_packet] Updated provider_npi: '{old_value}' -> '{npi_clean}'")
    
    # Provider Fax
    provider_fax = get_field_value(['Requester Fax', 'Provider Fax', 'Facility Provider Fax'])
    if provider_fax:
        # Normalize: digits only
        fax_clean = ''.join(c for c in str(provider_fax) if c.isdigit())
        if fax_clean:
            # Check if current value is None, empty, or TBD (case-insensitive)
            current_fax = packet.provider_fax or ""
            is_tbd_or_empty = not current_fax or current_fax.upper() == "TBD"
            if is_tbd_or_empty:
                packet.provider_fax = fax_clean
                packet_updated = True
    
    # Procedure Codes (individual columns)
    proc_code_1 = get_field_value(['Procedure Code set 1'])
    proc_code_2 = get_field_value(['Procedure Code set 2'])
    proc_code_3 = get_field_value(['Procedure Code set 3'])
    
    # Check if packet has procedure_code columns (may not exist in model)
    if hasattr(packet, 'procedure_code_1'):
        if proc_code_1 and (not packet.procedure_code_1 or packet.procedure_code_1 != proc_code_1):
            packet.procedure_code_1 = proc_code_1
            packet_updated = True
        if proc_code_2 and (not packet.procedure_code_2 or packet.procedure_code_2 != proc_code_2):
            packet.procedure_code_2 = proc_code_2
            packet_updated = True
        if proc_code_3 and (not packet.procedure_code_3 or packet.procedure_code_3 != proc_code_3):
            packet.procedure_code_3 = proc_code_3
            packet_updated = True
    
    # HCPCS (concatenated from procedure codes)
    proc_codes = [p for p in [proc_code_1, proc_code_2, proc_code_3] if p and p.strip()]
    if proc_codes:
        hcpcs_concatenated = ', '.join(proc_codes)
        if not packet.hcpcs or packet.hcpcs != hcpcs_concatenated:
            packet.hcpcs = hcpcs_concatenated
            packet_updated = True
    elif proc_code_1:  # Fallback: if only proc_code_1 exists, use it for HCPCS
        if not packet.hcpcs or packet.hcpcs != proc_code_1:
            packet.hcpcs = proc_code_1
            packet_updated = True
    
    # Submission Type (normalize values)
    submission_type_raw = get_field_value(['Submission Type', 'SubmissionType', 'Request Type'])
    if submission_type_raw:
        # Normalize: "expedited-initial" -> "Expedited", "standard-initial" -> "Standard"
        submission_type_normalized = None
        submission_lower = submission_type_raw.lower()
        if 'expedited' in submission_lower:
            submission_type_normalized = 'Expedited'
        elif 'standard' in submission_lower:
            submission_type_normalized = 'Standard'
        else:
            # Keep as-is if doesn't match known patterns
            submission_type_normalized = submission_type_raw
        
        if submission_type_normalized and (not packet.submission_type or packet.submission_type != submission_type_normalized):
            packet.submission_type = submission_type_normalized
            packet_updated = True
    
    # Update timestamp if packet was updated
    if packet_updated:
        packet.updated_at = now
        logger.info(
            f"[sync_packet] Packet {packet_external_id} updated. "
            f"Final values: beneficiary_name='{packet.beneficiary_name}', "
            f"beneficiary_mbi='{packet.beneficiary_mbi}', "
            f"provider_name='{packet.provider_name}', "
            f"provider_npi='{packet.provider_npi}'"
        )
    else:
        logger.info(
            f"[sync_packet] Packet {packet_external_id} not updated (no changes needed or no valid values found)"
        )
    
    return packet_updated

