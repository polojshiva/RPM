-- SQL Seed Script for service_ops schema in wiser_ops database
-- Generated from extracted mock data (packets, documents, letters, ocr_extraction, analytics_insights, clinical, outbound, users)
-- Date: 2025-12-28

-- 1. Users
INSERT INTO service_ops.users (id, username, password_hash, role) VALUES
  ('1', 'admin', '$2b$12$REPLACE_WITH_HASHED_ADMINPASS', 'ADMIN'),
  ('2', 'reviewer1', '$2b$12$REPLACE_WITH_HASHED_REVIEWER1PASS', 'REVIEWER'),
  ('3', 'reviewer2', '$2b$12$REPLACE_WITH_HASHED_REVIEWER2PASS', 'REVIEWER'),
  ('4', 'coordinator1', '$2b$12$REPLACE_WITH_HASHED_COORDINATOR1PASS', 'COORDINATOR'),
  ('5', 'coordinator2', '$2b$12$REPLACE_WITH_HASHED_COORDINATOR2PASS', 'COORDINATOR'),
  ('6', 'guest1', '$2b$12$REPLACE_WITH_HASHED_GUEST1PASS', 'GUEST');

-- 2. Packets (sample, expand as needed)
INSERT INTO service_ops.packets (
  id, patient_name, patient_dob, patient_mrn, patient_phone, patient_email, diagnosis, referring_provider, referring_provider_npi, insurance, status, assigned_to, created_at, updated_at, notes, high_level_status, detailed_status, review_type, completeness
) VALUES
  ('PKT-2025-001234', 'John Smith', '1975-01-15', 'MRN100001', '(555) 101-1001', 'patient0@example.com', 'Type 2 Diabetes Mellitus', 'Dr. Smith', '8084000005', 'Aetna', 'PENDING', '1', '2025-12-01 10:00:00', '2025-12-01 12:00:00', 'Initial intake notes for packet 1', 'INTAKE_PROCESSING', 'MANUAL_REVIEW', 'FIELDS', 95),
  ('PKT-2025-001235', 'Jane Doe', '1980-02-10', 'MRN100002', '(555) 102-1002', 'patient1@example.com', 'Hypertension', 'Dr. Johnson', '8084000006', 'Blue Cross Blue Shield', 'IN_REVIEW', NULL, '2025-12-02 11:00:00', '2025-12-02 13:00:00', NULL, 'CLINICAL_REVIEW', 'Pending Clinical Review', NULL, 88);

-- 3. Documents (sample, expand as needed)
INSERT INTO service_ops.documents (
  id, packet_id, file_name, document_type, page_count, file_size, uploaded_at, status, ocr_confidence, extracted_data
) VALUES
  ('DOC-001', 'PKT-2025-001234', 'PA_Request_Form.pdf', 'PA_REQUEST_FORM', 2, '245 KB', '2025-12-26T10:00:00Z', 'EXTRACTED', 98, TRUE),
  ('DOC-002', 'PKT-2025-001234', 'Physician_Order_Smith.pdf', 'PHYSICIAN_ORDER', 1, '156 KB', '2025-12-26T10:00:00Z', 'EXTRACTED', 95, TRUE),
  ('DOC-003', 'PKT-2025-001234', 'Medical_Records_2024.pdf', 'MEDICAL_RECORDS', 8, '1.2 MB', '2025-12-26T10:00:00Z', 'EXTRACTED', 87, TRUE);

-- 4. Letters (sample, expand as needed)
INSERT INTO service_ops.letters (
  id, packet_id, template_id, template_name, dismissal_reason, dismissal_reason_display, generated_at, generated_by, provider_name, provider_npi, provider_fax, provider_address_street, provider_address_city, provider_address_state, provider_address_zip, beneficiary_name, beneficiary_mbi, service_type, letter_content, status
) VALUES
  ('DL-001', 'PKT-2025-001250', 'DISM-TPL-001', 'Missing Documentation Notice', 'MISSING_DOCUMENTS', 'Missing Required Documents', '2025-12-28T08:00:00Z', 'Letter Generation System v2.1', 'Downtown Medical Center', '1112223334', '(555) 111-2222', '100 Medical Plaza Dr', 'Houston', 'TX', '77001', 'Michael Chen', '1WX2YZ3AB45', 'DME - Power Wheelchair', 'Dear Downtown Medical Center,\n\nRe: Prior Authorization Request - Dismissal Notice\nPatient: Michael Chen\nMBI: 1WX2YZ3AB45\nService: DME - Power Wheelchair (K0856)\n\nThis letter is to inform you that the prior authorization request submitted on behalf of the above-referenced beneficiary has been dismissed due to missing required documentation.\n\nThe following documents were not included with the submission:\n- Physician''s Order/Prescription\n- Face-to-Face Encounter Documentation\n- Medical Records (last 6 months)\n- Certificate of Medical Necessity (CMN)', 'PENDING');

-- 5. OCR Extractions (sample, expand as needed)
INSERT INTO service_ops.ocr_extractions (
  packet_id, medicare_part_type, submission_type, previous_utn, submitted_date, anticipated_date_of_service, location_of_service, beneficiary_last_name, beneficiary_first_name, medicare_id, beneficiary_dob, procedure_codes, modifiers, units, diagnosis_codes, facility_name, facility_npi, facility_ccn, facility_address1, facility_address2, facility_city, facility_state, facility_zip, physician_name, physician_npi, physician_ptan, physician_address, physician_city, physician_state, physician_zip, requester_name, requester_phone, requester_email, requester_fax, diagnosis_justification
) VALUES
  ('PKT-2025-001001', 'B', 'initial', '', '2025-12-15', '2025-12-20', 'office', 'Smlth', 'John', '1EG4TE5MK72', '1955-03-15', '{"L0450"}', '{""}', '{"1"}', '{"M54.5"}', 'ABC Medical Clinic', '123456789', '', '123 Medical Center Dr', 'Suite 200', 'Springfield', 'IL', '62701', 'Dr. Robert Johnson', '1234567890', 'ABC123', '456 Healthcare Blvd', 'Springfield', 'IL', '62702', 'Sarah Williams', '(555) 123-4567', 'swilliams@abcmedical.com', '(555) 123-4568', 'Patient presents with chronic low back pain requiring LSO support.');

-- 6. Outbound Deliveries, Clinical Cases, Analytics Insights
-- (Add similar INSERT statements for these entities based on extracted mock data)

-- 7. Analytics Insights (example, structure may vary)
-- INSERT INTO service_ops.analytics_insights (...columns...) VALUES (...);

-- 8. Clinical Cases (example, structure may vary)
-- INSERT INTO service_ops.clinical_cases (...columns...) VALUES (...);

-- 9. Outbound Deliveries (example, structure may vary)
-- INSERT INTO service_ops.outbound_deliveries (...columns...) VALUES (...);

-- NOTE: Replace $2b$12$REPLACE_WITH_HASHED_* with actual bcrypt hashes as needed.
-- Expand each section with all extracted mock data for full seeding.
-- Ensure all referenced IDs exist in related tables for foreign key integrity.
