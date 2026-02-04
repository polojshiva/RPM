-- SQL script to backfill packet table from OCR extracted_fields
-- This script extracts values from packet_document.extracted_fields JSONB
-- and updates the packet table for packets with TBD values
--
-- NOTE: This is for EXISTING packets that were processed before the persistence fix.
-- New packets processed after the fix will automatically have values persisted to packet table.
--
-- For a specific packet (replace PKT-2026-503899 with actual packet external_id):
DO $$
DECLARE
    v_packet_id BIGINT;
    v_doc_extracted_fields JSONB;
    v_fields JSONB;
    v_beneficiary_first_name TEXT;
    v_beneficiary_last_name TEXT;
    v_beneficiary_name TEXT;
    v_beneficiary_mbi TEXT;
    v_provider_name TEXT;
    v_facility_npi TEXT;
    v_physician_npi TEXT;
    v_provider_npi TEXT;
    v_npi_clean TEXT;
BEGIN
    -- Get packet_id
    SELECT packet_id INTO v_packet_id
    FROM service_ops.packet
    WHERE external_id = 'PKT-2026-503899';
    
    IF v_packet_id IS NULL THEN
        RAISE EXCEPTION 'Packet PKT-2026-503899 not found';
    END IF;
    
    -- Get extracted_fields from document
    SELECT extracted_fields INTO v_doc_extracted_fields
    FROM service_ops.packet_document
    WHERE packet_id = v_packet_id
    LIMIT 1;
    
    IF v_doc_extracted_fields IS NULL OR v_doc_extracted_fields->'fields' IS NULL THEN
        RAISE EXCEPTION 'No extracted_fields found for packet';
    END IF;
    
    v_fields := v_doc_extracted_fields->'fields';
    
    -- Extract beneficiary name (combine first + last)
    v_beneficiary_first_name := COALESCE(
        v_fields->'Beneficiary First Name'->>'value',
        v_fields->>'Beneficiary First Name'
    );
    v_beneficiary_last_name := COALESCE(
        v_fields->'Beneficiary Last Name'->>'value',
        v_fields->>'Beneficiary Last Name'
    );
    
    IF v_beneficiary_first_name IS NOT NULL AND v_beneficiary_last_name IS NOT NULL THEN
        v_beneficiary_name := TRIM(v_beneficiary_first_name || ' ' || v_beneficiary_last_name);
    ELSE
        v_beneficiary_name := COALESCE(
            v_fields->'Beneficiary Name'->>'value',
            v_fields->>'Beneficiary Name'
        );
    END IF;
    
    -- Extract beneficiary MBI
    v_beneficiary_mbi := COALESCE(
        v_fields->'Beneficiary Medicare ID'->>'value',
        v_fields->>'Beneficiary Medicare ID',
        v_fields->'Medicare ID'->>'value',
        v_fields->>'Medicare ID',
        v_fields->'MBI'->>'value',
        v_fields->>'MBI'
    );
    
    -- Extract provider name (prefer Facility Provider Name, then Attending Physician Name)
    v_provider_name := COALESCE(
        v_fields->'Facility Provider Name'->>'value',
        v_fields->>'Facility Provider Name',
        v_fields->'Attending Physician Name'->>'value',
        v_fields->>'Attending Physician Name',
        v_fields->'Provider Name'->>'value',
        v_fields->>'Provider Name'
    );
    
    -- Extract NPI (prefer Attending Physician NPI - 10 digits, over Facility Provider NPI - may be 9 digits)
    v_physician_npi := COALESCE(
        v_fields->'Attending Physician NPI'->>'value',
        v_fields->>'Attending Physician NPI'
    );
    v_facility_npi := COALESCE(
        v_fields->'Facility Provider NPI'->>'value',
        v_fields->>'Facility Provider NPI'
    );
    
    -- Use COALESCE to prefer physician_npi (10 digits) over facility_npi (may be 9 digits)
    v_provider_npi := COALESCE(v_physician_npi, v_facility_npi);
    
    -- Normalize NPI (remove non-digits, pad 9 digits with leading zero)
    IF v_provider_npi IS NOT NULL THEN
        v_npi_clean := REGEXP_REPLACE(v_provider_npi, '[^0-9]', '', 'g');
        IF LENGTH(v_npi_clean) = 9 THEN
            v_npi_clean := '0' || v_npi_clean;
        ELSIF LENGTH(v_npi_clean) != 10 THEN
            v_npi_clean := '0000000000';
        END IF;
    ELSE
        v_npi_clean := '0000000000';
    END IF;
    
    -- Update packet table (only if current value is TBD)
    UPDATE service_ops.packet
    SET
        beneficiary_name = CASE 
            WHEN beneficiary_name = 'TBD' OR beneficiary_name IS NULL THEN v_beneficiary_name
            ELSE beneficiary_name
        END,
        beneficiary_mbi = CASE 
            WHEN beneficiary_mbi = 'TBD' OR beneficiary_mbi IS NULL THEN v_beneficiary_mbi
            ELSE beneficiary_mbi
        END,
        provider_name = CASE 
            WHEN provider_name = 'TBD' OR provider_name IS NULL THEN v_provider_name
            ELSE provider_name
        END,
        provider_npi = CASE 
            WHEN provider_npi = 'TBD' OR provider_npi = '0000000000' OR provider_npi IS NULL THEN v_npi_clean
            ELSE provider_npi
        END,
        updated_at = NOW()
    WHERE packet_id = v_packet_id
    AND (
        beneficiary_name = 'TBD' OR beneficiary_mbi = 'TBD' OR 
        provider_name = 'TBD' OR provider_npi = 'TBD' OR provider_npi = '0000000000'
    );
    
    RAISE NOTICE 'Updated packet PKT-2026-503899:';
    RAISE NOTICE '  beneficiary_name: %', v_beneficiary_name;
    RAISE NOTICE '  beneficiary_mbi: %', v_beneficiary_mbi;
    RAISE NOTICE '  provider_name: %', v_provider_name;
    RAISE NOTICE '  provider_npi: %', v_npi_clean;
END $$;

