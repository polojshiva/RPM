"""
Document Converter
Converts PacketDocumentDB (SQLAlchemy) to PacketDocumentDTO (Pydantic)
"""
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone
from app.models.document_db import PacketDocumentDB
from app.models.document_dto import PacketDocumentDTO, DocumentType, DocumentStatus
from app.models.packet_db import PacketDB


def document_to_dto(document: PacketDocumentDB, packet_external_id: Optional[str] = None, db_session=None) -> PacketDocumentDTO:
    """
    Convert PacketDocumentDB (SQLAlchemy model) to PacketDocumentDTO for API response.
    
    Args:
        document: PacketDocumentDB instance
        packet_external_id: Optional packet external_id (if not provided, will query DB)
        db_session: Optional database session for lookups
    """
    # Get packet external_id if not provided
    if not packet_external_id and db_session:
        packet = db_session.query(PacketDB).filter(PacketDB.packet_id == document.packet_id).first()
        packet_external_id = packet.external_id if packet else f"SVC-{document.packet_id}"
    elif not packet_external_id:
        packet_external_id = f"SVC-{document.packet_id}"  # Fallback
    
    # Map document type - default to OTHER if not found
    # TODO: Join with document_type table to get actual type name
    document_type = DocumentType.OTHER
    if document.document_type_id:
        # For now, use a simple mapping or default
        # In production, you'd join with service_ops.document_type table
        document_type = DocumentType.OTHER
    
    # Map status - default based on extracted_data
    if document.extracted_data:
        doc_status = DocumentStatus.EXTRACTED
    elif document.ocr_confidence is not None:
        doc_status = DocumentStatus.PROCESSING
    else:
        doc_status = DocumentStatus.RECEIVED
    
    # Convert uploaded_at to ISO string
    uploaded_at_str = ""
    if document.uploaded_at:
        if isinstance(document.uploaded_at, datetime):
            if document.uploaded_at.tzinfo is None:
                uploaded_at_str = document.uploaded_at.replace(tzinfo=timezone.utc).isoformat()
            else:
                uploaded_at_str = document.uploaded_at.isoformat()
        else:
            uploaded_at_str = str(document.uploaded_at)
    
    # Convert updated_extracted_fields first (working view - primary source)
    # Then fallback to extracted_fields (baseline) if updated_extracted_fields is null
    # For backward compatibility, extractedFields in DTO will use updated_extracted_fields if available
    updated_extracted_fields_dict = None
    if document.updated_extracted_fields:
        if isinstance(document.updated_extracted_fields, dict):
            updated_extracted_fields_dict = document.updated_extracted_fields
        else:
            try:
                import json
                if isinstance(document.updated_extracted_fields, str):
                    updated_extracted_fields_dict = json.loads(document.updated_extracted_fields)
                else:
                    updated_extracted_fields_dict = document.updated_extracted_fields
            except:
                updated_extracted_fields_dict = None
    
    # Convert extracted_fields JSONB to dict (baseline - immutable)
    extracted_fields_dict = None
    if document.extracted_fields:
        # If it's already a dict, use it; otherwise try to parse it
        if isinstance(document.extracted_fields, dict):
            extracted_fields_dict = document.extracted_fields
        else:
            # If it's stored as a string or other format, try to convert
            try:
                import json
                if isinstance(document.extracted_fields, str):
                    extracted_fields_dict = json.loads(document.extracted_fields)
                else:
                    extracted_fields_dict = document.extracted_fields
            except:
                extracted_fields_dict = None
    
    # For backward compatibility: extractedFields should use updated_extracted_fields if available
    # (UI will read from updatedExtractedFields, but some old code may read extractedFields)
    extracted_fields_for_dto = updated_extracted_fields_dict if updated_extracted_fields_dict else extracted_fields_dict
    
    # Convert pages_metadata JSONB to dict (if present)
    pages_metadata_dict = None
    if document.pages_metadata:
        if isinstance(document.pages_metadata, dict):
            pages_metadata_dict = document.pages_metadata
        else:
            try:
                import json
                if isinstance(document.pages_metadata, str):
                    pages_metadata_dict = json.loads(document.pages_metadata)
                else:
                    pages_metadata_dict = document.pages_metadata
            except:
                pages_metadata_dict = None
    
    # Convert ocr_metadata JSONB to dict (if present)
    ocr_metadata_dict = None
    if document.ocr_metadata:
        if isinstance(document.ocr_metadata, dict):
            ocr_metadata_dict = document.ocr_metadata
        else:
            try:
                import json
                if isinstance(document.ocr_metadata, str):
                    ocr_metadata_dict = json.loads(document.ocr_metadata)
                else:
                    ocr_metadata_dict = document.ocr_metadata
            except:
                ocr_metadata_dict = None
    
    
    # Convert extracted_fields_update_history JSONB to list (if present) - audit trail
    update_history_list = None
    if document.extracted_fields_update_history:
        if isinstance(document.extracted_fields_update_history, list):
            update_history_list = document.extracted_fields_update_history
        else:
            try:
                import json
                if isinstance(document.extracted_fields_update_history, str):
                    update_history_list = json.loads(document.extracted_fields_update_history)
                else:
                    update_history_list = document.extracted_fields_update_history
            except:
                update_history_list = None
    
    # Convert suggested_extracted_fields JSONB to dict (if present) - OCR suggestion from rerun
    # Handle case where migration 007 may not have been run (column doesn't exist)
    suggested_extracted_fields_dict = None
    if hasattr(document, 'suggested_extracted_fields') and document.suggested_extracted_fields:
        if isinstance(document.suggested_extracted_fields, dict):
            suggested_extracted_fields_dict = document.suggested_extracted_fields
        else:
            try:
                import json
                if isinstance(document.suggested_extracted_fields, str):
                    suggested_extracted_fields_dict = json.loads(document.suggested_extracted_fields)
                else:
                    suggested_extracted_fields_dict = document.suggested_extracted_fields
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to parse suggested_extracted_fields: {e}")
                suggested_extracted_fields_dict = None
        
        # Log for debugging
        if suggested_extracted_fields_dict:
            import logging
            logger = logging.getLogger(__name__)
            fields_count = len(suggested_extracted_fields_dict.get('fields', {})) if isinstance(suggested_extracted_fields_dict, dict) else 0
            logger.info(f"document_to_dto: Converted suggested_extracted_fields with {fields_count} fields")
    
    # Derive filename from consolidated_blob_path if file_name is "consolidated.pdf" (legacy data)
    # This ensures UI shows correct filename even for old records
    display_file_name = document.file_name
    if document.file_name == "consolidated.pdf" and document.consolidated_blob_path:
        # Extract filename from blob path (e.g., "packet_12345.pdf")
        blob_filename = Path(document.consolidated_blob_path).name
        if blob_filename and blob_filename != "consolidated.pdf":
            display_file_name = blob_filename
    
    # Build PacketDocumentDTO
    return PacketDocumentDTO(
        id=document.external_id,
        packetId=packet_external_id,
        fileName=display_file_name,  # Use display_file_name instead of document.file_name
        documentType=document_type,
        pageCount=document.page_count or 0,
        fileSize=document.file_size or "0 KB",
        uploadedAt=uploaded_at_str,
        status=doc_status,
        ocrConfidence=document.ocr_confidence,
        extractedData=document.extracted_data,
        extractedFields=extracted_fields_for_dto,  # Backward compatibility: uses updated_extracted_fields if available
        thumbnailUrl=document.thumbnail_url,
        downloadUrl=document.download_url,
        # Page tracking and OCR metadata fields
        processingPath=document.processing_path,
        pagesMetadata=pages_metadata_dict,
        coversheetPageNumber=document.coversheet_page_number,
        partType=document.part_type,
        ocrMetadata=ocr_metadata_dict,
        splitStatus=document.split_status,
        ocrStatus=document.ocr_status,
        # Manual review and audit fields (added in migration 006)
        updatedExtractedFields=updated_extracted_fields_dict,
        extractedFieldsUpdateHistory=update_history_list,
        # OCR suggestion field (added in migration 007)
        suggestedExtractedFields=suggested_extracted_fields_dict,
        # Approved unit of service fields (added in migration 027)
        approvedUnitOfService1=document.approved_unit_of_service_1 if hasattr(document, 'approved_unit_of_service_1') else None,
        approvedUnitOfService2=document.approved_unit_of_service_2 if hasattr(document, 'approved_unit_of_service_2') else None,
        approvedUnitOfService3=document.approved_unit_of_service_3 if hasattr(document, 'approved_unit_of_service_3') else None,
    )


def documents_to_dto_list(documents: list[PacketDocumentDB], packet_external_id: Optional[str] = None, db_session=None) -> list[PacketDocumentDTO]:
    """Convert a list of PacketDocumentDB to PacketDocumentDTO"""
    return [document_to_dto(doc, packet_external_id, db_session) for doc in documents]

