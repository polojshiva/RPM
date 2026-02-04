"""
Document Routes
Operations for document pages and previews
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, status, Depends, Query, Body, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.services.db import get_db
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.api import ApiResponse
from app.models.packet_dto import PacketDTO, PacketDTOResponse
from app.models.document_dto import PacketDocumentDTO
from app.utils.packet_converter import packet_to_dto, extract_from_ocr_fields
from app.utils.document_converter import document_to_dto
from app.utils.blob_path_helper import resolve_blob_path, log_blob_access
from app.services.blob_storage import BlobStorageClient
from app.config.settings import settings
from typing import Optional, Dict, Any
import json
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/packets", tags=["Documents"])


def get_fields_with_priority(document: PacketDocumentDB) -> Optional[Dict[str, Any]]:
    """
    Get extracted fields with priority: updated_extracted_fields first (working copy), 
    then extracted_fields (baseline).
    
    This is the standard pattern throughout the application - always check 
    updated_extracted_fields first, fallback to extracted_fields.
    
    Args:
        document: PacketDocumentDB instance
        
    Returns:
        Dictionary with fields, or None if both are empty
    """
    if document.updated_extracted_fields:
        return document.updated_extracted_fields
    return document.extracted_fields


# Import sync function from utility to avoid circular imports
from app.utils.packet_sync import sync_packet_from_extracted_fields


@router.get("/{packet_id}/documents/{doc_id}/pages")
async def get_document_pages(
    packet_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all pages for a document.
    Returns list of pages with metadata.
    """
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Get pages metadata
    if not document.pages_metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pages metadata not available"
        )
    
    pages = document.pages_metadata.get('pages', [])
    
    # Convert to API format
    page_list = []
    for page in pages:
        page_list.append({
            'page_num': page.get('page_number'),
            'relative_path': page.get('relative_path') or page.get('blob_path'),
            'blob_path': page.get('blob_path') or page.get('relative_path'),
            'file_size_bytes': page.get('file_size_bytes', 0),
            'sha256': page.get('sha256'),
            'content_type': page.get('content_type', 'application/pdf'),
            'is_coversheet': page.get('is_coversheet', False),
            'ocr_confidence': page.get('ocr_confidence'),
        })
    
    return ApiResponse(
        success=True,
        data=page_list,
        message=f"Retrieved {len(page_list)} page(s) for document {doc_id}"
    )


@router.get("/{packet_id}/documents/{doc_id}/pages/{page_num}/preview")
async def get_page_preview_url(
    packet_id: str,
    doc_id: str,
    page_num: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get preview URL for a specific document page.
    Returns a proxy URL that serves the blob content with authentication.
    """
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Get pages metadata
    if not document.pages_metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pages metadata not available"
        )
    
    pages = document.pages_metadata.get('pages', [])
    page = next((p for p in pages if p.get('page_number') == page_num), None)
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_num} not found"
        )
    
    # Get blob path
    blob_path = page.get('blob_path') or page.get('relative_path')
    if not blob_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blob path not available for this page"
        )
    
    # Return proxy URL instead of trying to generate signed URL
    # The proxy endpoint will handle authentication and blob access
    try:
        # CRITICAL FIX: Use url_for() to generate URL with correct scheme
        # This respects X-Forwarded-Proto header (via ProxyHeadersMiddleware)
        # Fallback to PUBLIC_BASE_URL if set (for Gov environments)
        
        if settings.public_base_url:
            # Use explicit base URL from environment (for deterministic behavior in Gov)
            base_url = settings.public_base_url.rstrip('/')
            preview_url = f"{base_url}/api/packets/{packet_id}/documents/{doc_id}/pages/{page_num}/content"
            logger.debug(f"Using PUBLIC_BASE_URL for preview URL: {preview_url}")
        else:
            # Use url_for() which respects ProxyHeadersMiddleware and X-Forwarded-Proto
            preview_url = str(request.url_for(
                "get_page_content",
                packet_id=packet_id,
                doc_id=doc_id,
                page_num=page_num
            ))
            logger.debug(f"Using url_for() for preview URL: {preview_url}")
        
        logger.info(f"Resolved preview URL for page {page_num}: {preview_url}")
        
        return ApiResponse(
            success=True,
            data={
                "previewUrl": preview_url,
                "thumbnailUrl": None  # Thumbnails not implemented yet
            },
            message="Page preview URL retrieved successfully"
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Failed to resolve preview URL for page {page_num}: {str(e)}\n{error_details}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to resolve preview URL: {str(e)}"
        )


@router.get("/{packet_id}/documents/{doc_id}/pages/{page_num}/content", name="get_page_content")
async def get_page_content(
    packet_id: str,
    doc_id: str,
    page_num: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Proxy endpoint to serve blob content with authentication.
    This endpoint streams the blob content to the client, handling authentication
    on the backend using Managed Identity or connection string.
    """
    logger.info(
        f"Content endpoint called: packet_id={packet_id}, doc_id={doc_id}, page_num={page_num}, "
        f"user={current_user.username if current_user else 'unknown'}"
    )
    
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Get pages metadata
    if not document.pages_metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pages metadata not available"
        )
    
    pages = document.pages_metadata.get('pages', [])
    page = next((p for p in pages if p.get('page_number') == page_num), None)
    
    if not page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_num} not found"
        )
    
    # Get blob path from pages_metadata
    # The blob_path stored in DB may or may not include the prefix depending on when it was created
    # We'll normalize it to a relative path and let the helper apply the prefix consistently
    blob_path = page.get('blob_path') or page.get('relative_path')
    if not blob_path:
        logger.error(f"Page {page_num} missing blob_path and relative_path in pages_metadata")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blob path not available for this page"
        )
    
    # Normalize blob path - remove leading slashes
    blob_path = blob_path.lstrip('/')
    
    # Strip any existing prefix that might be in the stored path
    # This handles legacy data where prefix was stored in the DB
    # We want to work with the relative path and let the helper add the prefix consistently
    if blob_path.startswith('service_ops_processing/'):
        blob_path = blob_path[len('service_ops_processing/'):]
        logger.debug(f"Stripped 'service_ops_processing/' prefix from stored blob_path")
    elif blob_path.startswith('service-ops-processing/'):
        blob_path = blob_path[len('service-ops-processing/'):]
        logger.debug(f"Stripped 'service-ops-processing/' prefix from stored blob_path")
    
    # Now blob_path is relative to container root, e.g., "2026/01-06/.../page_0001.pdf"
    # The resolve_blob_path helper will add the prefix if configured
    
    # Use DEST container (service-ops-processing) where split pages are stored
    container_name = settings.azure_storage_dest_container
    if not container_name:
        logger.error("AZURE_STORAGE_DEST_CONTAINER not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Azure storage DEST container not configured"
        )
    
    # Resolve blob path with prefix helper
    resolved_blob_path = resolve_blob_path(blob_path)
    
    # Log blob access with context
    log_blob_access(
        container_name=container_name,
        resolved_blob_path=resolved_blob_path,
        packet_id=packet_id,
        doc_id=doc_id,
        page_num=page_num
    )
    
    try:
        blob_client = BlobStorageClient(
            storage_account_url=settings.storage_account_url,
            container_name=container_name,
            connection_string=settings.azure_storage_connection_string
        )
        
        # Get blob client - pass the already-resolved blob path to avoid double prefix
        # The _get_blob_client method will handle URL resolution but should not add prefix again
        # since we've already resolved it above
        blob_storage_client = blob_client._get_blob_client(resolved_blob_path, container_name=container_name)
        
        # Log the extracted container and blob name for verification
        logger.debug(
            f"BlobClient created: container='{blob_storage_client.container_name}', "
            f"blob_name='{blob_storage_client.blob_name}'"
        )
        
        # Verify blob exists and get properties
        try:
            properties = blob_storage_client.get_blob_properties()
            content_type = properties.content_settings.content_type if properties.content_settings else 'application/pdf'
            blob_size = properties.size
            logger.info(
                f"Blob found: size={blob_size} bytes, content_type={content_type}, "
                f"etag={properties.etag}"
            )
        except Exception as e:
            # Log detailed error for debugging
            resolved_url = blob_client.resolve_blob_url(blob_path, container_name=container_name)
            logger.error(
                f"Blob not found or inaccessible: original_blob_path='{blob_path}', "
                f"resolved_blob_path='{resolved_blob_path}', container='{container_name}', "
                f"resolved_url='{resolved_url}', error={str(e)}", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Blob not found: {blob_path} in container {container_name}"
            )
        
        # Stream blob content directly from download stream
        # This is the most efficient approach - streams chunks without loading entire file into memory
        def generate():
            try:
                logger.info(f"Starting to stream blob content for page {page_num}")
                download_stream = blob_storage_client.download_blob()
                
                # Stream in chunks for efficient transmission
                chunk_size = 8192  # 8KB chunks
                bytes_streamed = 0
                
                while True:
                    chunk = download_stream.read(chunk_size)
                    if not chunk:
                        break
                    bytes_streamed += len(chunk)
                    yield chunk
                
                logger.info(
                    f"Successfully streamed {bytes_streamed} bytes for page {page_num} "
                    f"(expected: {blob_size} bytes)"
                )
                
            except Exception as e:
                logger.error(
                    f"Error streaming blob content for page {page_num}: {e}",
                    exc_info=True
                )
                # Note: Can't raise HTTPException from generator, but error will be logged
                # The client will see a connection error or blank page
                return
        
        # Return streaming response with appropriate headers
        # CRITICAL: Set Content-Length header for proper browser handling in government cloud
        response_headers = {
            "Content-Disposition": f'inline; filename="page_{page_num}.pdf"',
            "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
            "Accept-Ranges": "bytes",  # Support range requests
            "X-Frame-Options": "SAMEORIGIN",  # Allow iframe embedding from same origin (overrides global DENY)
        }
        
        # Add Content-Length if we have blob size (helps browsers handle the response correctly)
        if blob_size > 0:
            response_headers["Content-Length"] = str(blob_size)
        
        return StreamingResponse(
            generate(),
            media_type=content_type,
            headers=response_headers
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(
            f"Failed to stream blob content for page {page_num}: original_blob_path='{blob_path}', "
            f"resolved_blob_path='{resolved_blob_path}', container='{container_name}', "
            f"error={str(e)}\n{error_details}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stream blob content: {str(e)}"
        )


@router.put("/{packet_id}/documents/{doc_id}/extracted-fields")
async def update_extracted_fields(
    packet_id: str,
    doc_id: str,
    fields_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update extracted fields for a document with full audit trail.
    
    Supports manual correction of OCR-extracted field values with:
    - Update of extracted_fields (working view)
    - Creation of updated_extracted_fields snapshot (audit)
    - Append-only audit history in extracted_fields_update_history
    - Automatic update of packet table for mapped fields (beneficiary, provider, NPI, MBI)
    
    Request body format:
    {
        "fields": {
            "Beneficiary Name": "John Doe",
            "Provider NPI": "1234567890",
            ...
        }
    }
    """
    now = datetime.now(timezone.utc)
    username = current_user.username if current_user else "unknown"
    
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Initialize updated_extracted_fields if missing (working view)
    # Fallback to extracted_fields if updated_extracted_fields doesn't exist yet
    if not document.updated_extracted_fields:
        if document.extracted_fields:
            # Copy from baseline if available
            document.updated_extracted_fields = document.extracted_fields.copy()
        else:
            document.updated_extracted_fields = {'fields': {}, 'raw': {}}
    
    # Ensure 'fields' key exists in working view
    if 'fields' not in document.updated_extracted_fields:
        document.updated_extracted_fields['fields'] = {}
    
    # Handle approved unit of service fields separately (not in extracted_fields)
    approved_unit_1 = fields_data.get('approvedUnitOfService1')
    approved_unit_2 = fields_data.get('approvedUnitOfService2')
    approved_unit_3 = fields_data.get('approvedUnitOfService3')
    
    # Track if approved unit fields changed
    approved_unit_changes = False
    if hasattr(document, 'approved_unit_of_service_1'):
        if approved_unit_1 is not None and str(document.approved_unit_of_service_1 or '').strip() != str(approved_unit_1 or '').strip():
            document.approved_unit_of_service_1 = str(approved_unit_1).strip() if approved_unit_1 else None
            approved_unit_changes = True
        if approved_unit_2 is not None and str(document.approved_unit_of_service_2 or '').strip() != str(approved_unit_2 or '').strip():
            document.approved_unit_of_service_2 = str(approved_unit_2).strip() if approved_unit_2 else None
            approved_unit_changes = True
        if approved_unit_3 is not None and str(document.approved_unit_of_service_3 or '').strip() != str(approved_unit_3 or '').strip():
            document.approved_unit_of_service_3 = str(approved_unit_3).strip() if approved_unit_3 else None
            approved_unit_changes = True
    
    # Parse incoming fields (support both dict and array formats)
    incoming_fields_raw = fields_data.get('fields', {})
    incoming_fields = {}
    
    logger.info(f"[update_extracted_fields] Raw incoming fields_data: {fields_data}")
    logger.info(f"[update_extracted_fields] incoming_fields_raw type: {type(incoming_fields_raw)}, value: {incoming_fields_raw}")
    
    if isinstance(incoming_fields_raw, list):
        # Format B: [{"name": "Field Name", "value": "value"}]
        for item in incoming_fields_raw:
            if isinstance(item, dict) and 'name' in item:
                incoming_fields[item['name']] = item.get('value', '')
    else:
        # Format A: {"Field Name": "value"} or {"Field Name": {"value": "value", ...}}
        for field_name, field_value in incoming_fields_raw.items():
            logger.info(f"[update_extracted_fields] Parsing field '{field_name}': type={type(field_value)}, value={field_value}")
            if isinstance(field_value, dict):
                incoming_fields[field_name] = field_value.get('value', '')
            else:
                incoming_fields[field_name] = field_value
    
    logger.info(f"[update_extracted_fields] Parsed incoming_fields: {incoming_fields}")
    logger.info(f"[update_extracted_fields] Incoming fields keys: {list(incoming_fields.keys())}")
    logger.info(f"[update_extracted_fields] Existing fields keys: {list(document.updated_extracted_fields.get('fields', {}).keys())}")
    
    # Step 1: Compute changed_fields diff (compare against working view)
    changed_fields = {}
    existing_fields = document.updated_extracted_fields.get('fields', {})
    
    for field_name, new_value in incoming_fields.items():
        # Normalize values for comparison
        new_value_str = str(new_value).strip() if new_value else ""
        
        # Get old value
        old_value = ""
        if field_name in existing_fields:
            field_data = existing_fields[field_name]
            if isinstance(field_data, dict):
                old_value = str(field_data.get('value', '')).strip()
            else:
                old_value = str(field_data).strip()
        
        # Only track if changed
        if old_value != new_value_str:
            changed_fields[field_name] = {
                'old': old_value,
                'new': new_value_str
            }
    
    # If no changes in extracted fields AND no approved unit changes, return early
    if not changed_fields and not approved_unit_changes:
        logger.info(f"No changes detected for document {doc_id}")
        document_dto = document_to_dto(document, packet_id, db)
        packet_dto = packet_to_dto(packet, db_session=db)
        return ApiResponse(
            success=True,
            data={
                'packet': packet_dto.dict(),
                'document': document_dto.dict(),
                'message': 'No changes detected'
            },
            message="No changes to save"
        )
    
    # Step 2: Apply edits to updated_extracted_fields.fields (preserve confidence, add source flag)
    # DO NOT modify extracted_fields (it's immutable baseline)
    for field_name, new_value in incoming_fields.items():
        logger.info(f"[update_extracted_fields] Processing field '{field_name}': raw_value={repr(new_value)}, type={type(new_value)}")
        new_value_str = str(new_value).strip() if new_value else ""
        logger.info(f"[update_extracted_fields] Field '{field_name}' after processing: new_value_str={repr(new_value_str)}")
        
        if field_name in existing_fields:
            # Update existing field - preserve confidence and type, update value, add source
            field_data = existing_fields[field_name]
            if isinstance(field_data, dict):
                existing_fields[field_name] = {
                    **field_data,
                    'value': new_value_str,
                    'source': 'MANUAL'  # Flag indicating manual edit
                }
            else:
                # Convert to dict format
                existing_fields[field_name] = {
                    'value': new_value_str,
                    'confidence': 1.0,  # Manual edits get full confidence
                    'field_type': 'DocumentFieldType.STRING',
                    'source': 'MANUAL'
                }
        else:
            # New field - create dict structure
            existing_fields[field_name] = {
                'value': new_value_str,
                'confidence': 1.0,
                'field_type': 'DocumentFieldType.STRING',
                'source': 'MANUAL'
            }
    
    # CRITICAL: Assign modified existing_fields back to document.updated_extracted_fields['fields']
    # This ensures the changes are persisted to the database
    # DO NOT modify document.extracted_fields (it's immutable baseline)
    document.updated_extracted_fields['fields'] = existing_fields
    
    # Preserve raw OCR data if it exists (copy from baseline if needed)
    if 'raw' not in document.updated_extracted_fields:
        if document.extracted_fields and 'raw' in document.extracted_fields:
            document.updated_extracted_fields['raw'] = document.extracted_fields.get('raw', {})
        else:
            document.updated_extracted_fields['raw'] = {}
    
    # Step 3: Build final_payload for updated_extracted_fields only
    final_payload = {
        **document.updated_extracted_fields,  # Base structure (includes fields after edits)
        'last_updated_at': now.isoformat(),
        'last_updated_by': username,
        'source': 'MANUAL'
    }
    
    # CRITICAL: Update ONLY updated_extracted_fields (working view)
    # DO NOT modify extracted_fields (it's immutable baseline)
    document.updated_extracted_fields = final_payload
    flag_modified(document, 'updated_extracted_fields')
    
    logger.info(f"[update_extracted_fields] ✓ Updated updated_extracted_fields (working view)")
    logger.info(f"[update_extracted_fields] ✓ Preserved extracted_fields (baseline unchanged)")
    
    # Step 4: Append audit entry to extracted_fields_update_history
    if not document.extracted_fields_update_history:
        document.extracted_fields_update_history = []
    
    audit_entry = {
        'type': 'MANUAL_SAVE',
        'updated_at': now.isoformat(),
        'updated_by': username,
        'changed_fields': changed_fields,
        'note': 'Manual field update'
    }
    document.extracted_fields_update_history.append(audit_entry)
    flag_modified(document, 'extracted_fields_update_history')  # Also flag this JSONB column
    
    # Step 5: Apply auto-fix to updated fields (silent formatting fixes)
    try:
        from app.services.field_auto_fix import apply_auto_fix_to_fields
        fixed_fields, auto_fix_results = apply_auto_fix_to_fields(document.updated_extracted_fields)
        document.updated_extracted_fields = fixed_fields
        flag_modified(document, 'updated_extracted_fields')
        
        # Store auto-fix results in extracted_fields for tracking
        if auto_fix_results:
            if 'auto_fix_applied' not in document.updated_extracted_fields:
                document.updated_extracted_fields['auto_fix_applied'] = {}
            document.updated_extracted_fields['auto_fix_applied'].update(auto_fix_results)
            flag_modified(document, 'updated_extracted_fields')
            logger.info(f"[update_extracted_fields] Applied auto-fix to {len(auto_fix_results)} field(s)")
    except Exception as e:
        logger.warning(f"[update_extracted_fields] Error applying auto-fix: {str(e)}. Continuing without auto-fix.")
    
    # Step 6: Sync packet table with updated fields (HCPCS, procedure codes, submission_type, etc.)
    logger.info(
        f"[update_extracted_fields] Calling sync_packet_from_extracted_fields for packet {packet.external_id}. "
        f"Packet current values before sync: beneficiary_name='{packet.beneficiary_name}', "
        f"beneficiary_mbi='{packet.beneficiary_mbi}', provider_name='{packet.provider_name}', "
        f"provider_npi='{packet.provider_npi}'"
    )
    
    packet_updated = sync_packet_from_extracted_fields(packet, document.updated_extracted_fields, now, db)
    
    logger.info(
        f"[update_extracted_fields] Sync result: packet_updated={packet_updated}. "
        f"Packet values after sync (before commit): beneficiary_name='{packet.beneficiary_name}', "
        f"beneficiary_mbi='{packet.beneficiary_mbi}', provider_name='{packet.provider_name}', "
        f"provider_npi='{packet.provider_npi}'"
    )
    
    # CRITICAL: Flush to ensure SQLAlchemy tracks the changes before commit
    if packet_updated:
        db.flush()
        logger.info(f"[update_extracted_fields] Flushed packet changes to database session")
    
    # Step 7: Run field validation
    try:
        from app.services.field_validation_service import validate_all_fields
        from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag
        
        validation_result = validate_all_fields(
            extracted_fields=document.updated_extracted_fields,
            packet=packet,
            db_session=db
        )
        
        # Save validation results
        save_field_validation_errors(
            packet_id=packet.packet_id,
            validation_result=validation_result,
            db_session=db
        )
        
        # Update packet flag
        update_packet_validation_flag(
            packet_id=packet.packet_id,
            has_errors=validation_result['has_errors'],
            db_session=db
        )
        
        logger.info(
            f"[update_extracted_fields] Validation complete. has_errors={validation_result['has_errors']}, "
            f"error_count={len(validation_result.get('field_errors', {}))}"
        )
    except Exception as e:
        logger.error(f"[update_extracted_fields] Error running validation: {str(e)}. Continuing without validation.")
    
    # Update document timestamp (also update if only approved unit fields changed)
    if approved_unit_changes:
      document.updated_at = now
    elif changed_fields:
      document.updated_at = now
    
    # Step 8: Save transaction
    try:
        db.commit()
        logger.info(
            f"[update_extracted_fields] Committed transaction. Packet values after commit (before refresh): "
            f"beneficiary_name='{packet.beneficiary_name}', beneficiary_mbi='{packet.beneficiary_mbi}', "
            f"provider_name='{packet.provider_name}', provider_npi='{packet.provider_npi}'"
        )
        db.refresh(document)
        db.refresh(packet)
        
        logger.info(
            f"[update_extracted_fields] After refresh - Packet values from DB: "
            f"beneficiary_name='{packet.beneficiary_name}', beneficiary_mbi='{packet.beneficiary_mbi}', "
            f"provider_name='{packet.provider_name}', provider_npi='{packet.provider_npi}'"
        )
        
        # CRITICAL: Verify that updated_extracted_fields.fields was updated
        # Verify that extracted_fields.fields was NOT modified (baseline preserved)
        saved_updated_fields = document.updated_extracted_fields.get('fields', {}) if document.updated_extracted_fields else {}
        saved_baseline_fields = document.extracted_fields.get('fields', {}) if document.extracted_fields else {}
        logger.info(f"[update_extracted_fields] After commit - updated_extracted_fields.fields keys: {list(saved_updated_fields.keys())}")
        logger.info(f"[update_extracted_fields] After commit - extracted_fields.fields keys (baseline, should be unchanged): {list(saved_baseline_fields.keys())}")
        for field_name in changed_fields.keys():
            updated_field_data = saved_updated_fields.get(field_name)
            baseline_field_data = saved_baseline_fields.get(field_name)
            if updated_field_data:
                logger.info(
                    f"[update_extracted_fields] ✓ Field '{field_name}' in updated_extracted_fields.fields: "
                    f"value='{updated_field_data.get('value', 'NOT FOUND')}', source={updated_field_data.get('source', 'N/A')}"
                )
            else:
                logger.error(f"[update_extracted_fields] ✗ Field '{field_name}' NOT FOUND in updated_extracted_fields.fields after save!")
            # Verify baseline was not modified
            if baseline_field_data:
                baseline_value = baseline_field_data.get('value', '') if isinstance(baseline_field_data, dict) else str(baseline_field_data)
                updated_value = updated_field_data.get('value', '') if updated_field_data and isinstance(updated_field_data, dict) else ''
                if baseline_value != updated_value:
                    logger.info(f"[update_extracted_fields] ✓ Baseline preserved: '{field_name}' baseline='{baseline_value}' vs updated='{updated_value}'")
                else:
                    logger.warning(f"[update_extracted_fields] ⚠ Baseline and updated have same value for '{field_name}' (may be initial state)")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to save extracted fields update: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save changes: {str(e)}"
        )
    
    # Step 7: Return updated DTOs
    document_dto = document_to_dto(document, packet_id, db)
    packet_dto = packet_to_dto(packet, db_session=db)
    
    # CRITICAL: Verify what's being returned to frontend (should read from updatedExtractedFields)
    dto_updated_fields = document_dto.updatedExtractedFields.get('fields', {}) if document_dto.updatedExtractedFields else {}
    logger.info(f"[update_extracted_fields] DTO updatedExtractedFields.fields keys: {list(dto_updated_fields.keys())}")
    for field_name in changed_fields.keys():
        field_data = dto_updated_fields.get(field_name)
        if field_data:
            logger.info(
                f"[update_extracted_fields] ✓ Field '{field_name}' in DTO updatedExtractedFields: "
                f"value='{field_data.get('value', 'NOT FOUND')}', source={field_data.get('source', 'N/A')}"
            )
        else:
            logger.error(f"[update_extracted_fields] ✗ Field '{field_name}' NOT FOUND in DTO updatedExtractedFields.fields!")
    
    logger.info(
        f"Updated extracted fields for document {doc_id}: {len(changed_fields)} field(s) changed. "
        f"Updated updated_extracted_fields (working view), preserved extracted_fields (baseline)."
    )
    
    return ApiResponse(
        success=True,
        data={
            'packet': packet_dto.dict(),
            'document': document_dto.dict(),
            'changed_fields': list(changed_fields.keys()),
            'message': f'Updated {len(changed_fields)} field(s) successfully'
        },
        message="Extracted fields updated successfully"
    )


@router.post("/{packet_id}/documents/{doc_id}/apply-ocr")
async def apply_ocr_to_working(
    packet_id: str,
    doc_id: str,
    request_body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    DEPRECATED: This endpoint has been removed as part of simplification.
    Use "Mark as Coversheet" to rerun OCR and replace working fields.
    """
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Endpoint deprecated. Use 'Mark as Coversheet' to rerun OCR."
    )
    """
    Apply New OCR snapshot to working fields (extracted_fields and updated_extracted_fields).
    
    This endpoint promotes OCR results from suggested_extracted_fields into the working view,
    overwriting existing values. User can optionally provide field overrides.
    
    Request body format:
    {
        "fields": {  // optional - field overrides if user edited in New OCR tab
            "<Field Name>": "<value>",
            ...
        },
        "mode": "FULL"  // fixed for now
    }
    
    Behavior:
    1. Loads New OCR snapshot from suggested_extracted_fields
    2. Applies optional field overrides from request body
    3. Builds final_payload with source="OCR_APPLIED"
    4. Overwrites BOTH extracted_fields and updated_extracted_fields (synchronized)
    5. Appends history entry with type="OCR_APPLIED"
    6. Syncs packet table fields
    7. Returns updated document DTO
    """
    now = datetime.now(timezone.utc)
    username = current_user.username if current_user else "unknown"
    
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Verify New OCR snapshot exists
    if not document.suggested_extracted_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No New OCR snapshot available. Please mark a page as coversheet or rerun OCR first."
        )
    
    new_ocr_snapshot = document.suggested_extracted_fields
    if not isinstance(new_ocr_snapshot, dict) or 'fields' not in new_ocr_snapshot:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New OCR snapshot is invalid or missing fields"
        )
    
    # Get field overrides from request body (optional)
    field_overrides = request_body.get('fields', {})
    mode = request_body.get('mode', 'FULL')
    
    logger.info(f"[apply_ocr] Applying OCR for document {doc_id} with {len(field_overrides)} field override(s)")
    
    # Build final_fields: start with OCR fields, apply overrides
    new_ocr_fields = new_ocr_snapshot.get('fields', {})
    final_fields = {}
    
    # Copy all OCR fields first
    for field_name, field_data in new_ocr_fields.items():
        if isinstance(field_data, dict):
            # Preserve OCR confidence and metadata, but mark source if overridden
            final_fields[field_name] = {
                **field_data,
                'source': 'MANUAL_ON_OCR' if field_name in field_overrides else field_data.get('source', 'OCR')
            }
        else:
            # Convert to dict format
            final_fields[field_name] = {
                'value': str(field_data) if field_data else '',
                'confidence': new_ocr_snapshot.get('overall_document_confidence', 0.0),
                'field_type': 'DocumentFieldType.STRING',
                'source': 'MANUAL_ON_OCR' if field_name in field_overrides else 'OCR'
            }
    
    # Apply overrides
    for field_name, override_value in field_overrides.items():
        override_value_str = str(override_value).strip() if override_value else ""
        if field_name in final_fields:
            # Update existing field - preserve confidence from OCR if available
            field_data = final_fields[field_name]
            if isinstance(field_data, dict):
                final_fields[field_name] = {
                    **field_data,
                    'value': override_value_str,
                    'source': 'MANUAL_ON_OCR'
                }
            else:
                final_fields[field_name] = {
                    'value': override_value_str,
                    'confidence': new_ocr_snapshot.get('overall_document_confidence', 0.0),
                    'field_type': 'DocumentFieldType.STRING',
                    'source': 'MANUAL_ON_OCR'
                }
        else:
            # New field from override
            final_fields[field_name] = {
                'value': override_value_str,
                'confidence': 1.0,  # Manual overrides get full confidence
                'field_type': 'DocumentFieldType.STRING',
                'source': 'MANUAL_ON_OCR'
            }
    
    # Build final_payload (must be written to BOTH extracted_fields and updated_extracted_fields)
    now_iso = now.isoformat()
    final_payload = {
        'fields': final_fields,
        'coversheet_type': new_ocr_snapshot.get('coversheet_type', ''),
        'doc_type': new_ocr_snapshot.get('doc_type', ''),
        'overall_document_confidence': new_ocr_snapshot.get('overall_document_confidence', 0.0),
        'duration_ms': new_ocr_snapshot.get('duration_ms', 0),
        'page_number': document.coversheet_page_number or new_ocr_snapshot.get('page_number'),
        'raw': new_ocr_snapshot.get('raw', {}),
        'source': 'OCR_APPLIED',
        'last_updated_at': now_iso,
        'last_updated_by': username
    }
    
    # Compute changed_fields for history (compare previous extracted_fields with final_fields)
    previous_fields = {}
    if document.extracted_fields and isinstance(document.extracted_fields, dict):
        prev_fields_dict = document.extracted_fields.get('fields', {})
        for field_name, field_data in prev_fields_dict.items():
            if isinstance(field_data, dict):
                previous_fields[field_name] = str(field_data.get('value', '')).strip()
            else:
                previous_fields[field_name] = str(field_data).strip()
    
    changed_fields = {}
    for field_name, field_data in final_fields.items():
        new_value = str(field_data.get('value', '') if isinstance(field_data, dict) else field_data).strip()
        old_value = previous_fields.get(field_name, '').strip()
        if old_value != new_value:
            changed_fields[field_name] = {
                'old': old_value,
                'new': new_value
            }
    
    # Overwrite BOTH columns (synchronized)
    document.extracted_fields = final_payload
    document.updated_extracted_fields = final_payload
    flag_modified(document, 'extracted_fields')
    flag_modified(document, 'updated_extracted_fields')
    
    # Append history entry
    if not document.extracted_fields_update_history:
        document.extracted_fields_update_history = []
    
    history_entry = {
        'type': 'OCR_APPLIED',
        'updated_at': now_iso,
        'updated_by': username,
        'coversheet_page_number': document.coversheet_page_number,
        'changed_fields': changed_fields,
        'note': 'Applied New OCR to Working'
    }
    document.extracted_fields_update_history.append(history_entry)
    flag_modified(document, 'extracted_fields_update_history')
    
    # Sync packet table - use fields with priority (updated_extracted_fields first)
    fields_dict = get_fields_with_priority(document)
    packet_updated = sync_packet_from_extracted_fields(packet, fields_dict, now, db) if fields_dict else False
    
    # Update timestamps
    document.updated_at = now
    
    # Commit transaction
    try:
        db.commit()
        db.refresh(document)
        db.refresh(packet)
        
        logger.info(
            f"[apply_ocr] Applied OCR for document {doc_id}: {len(changed_fields)} field(s) changed. "
            f"Packet updated: {packet_updated}"
        )
    except Exception as e:
        db.rollback()
        logger.error(f"[apply_ocr] Failed to apply OCR: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply OCR: {str(e)}"
        )
    
    # Return updated DTOs
    document_dto = document_to_dto(document, packet_id, db)
    packet_dto = packet_to_dto(packet, db_session=db)
    
    return ApiResponse(
        success=True,
        data={
            'packet': packet_dto.dict(),
            'document': document_dto.dict(),
            'changed_fields': list(changed_fields.keys()),
            'message': f'Applied OCR: {len(changed_fields)} field(s) updated'
        },
        message="OCR applied successfully"
    )


@router.post("/{packet_id}/documents/{doc_id}/trigger-ocr")
async def trigger_ocr(
    packet_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Trigger OCR processing programmatically for a document.
    
    This endpoint allows programmatic OCR triggering for documents that have been split
    but OCR has not been run yet (ocr_status = 'NOT_STARTED').
    
    Prerequisites:
    - Document must have split_status = 'DONE' (pages must be split)
    - Document must have pages_metadata with page blob paths
    - Document must not have ocr_status = 'IN_PROGRESS' (concurrency guard)
    
    Flow:
    1. Validates prerequisites
    2. Downloads all pages from blob storage to temp files
    3. Creates SplitResult from downloaded pages
    4. Calls DocumentProcessor._process_ocr() to run OCR on all pages
    5. Updates extracted_fields, coversheet_page_number, part_type in database
    6. Returns success response with updated document info
    
    Returns:
    {
        "success": true,
        "message": "OCR processing completed successfully",
        "data": {
            "document_id": "DOC-1046",
            "ocr_status": "DONE",
            "coversheet_page_number": 1,
            "part_type": "PART_A",
            "fields_count": 25
        }
    }
    """
    import tempfile
    import uuid
    from pathlib import Path
    from app.services.document_processor import DocumentProcessor
    from app.services.document_processor_resume import get_page_blob_paths_from_metadata
    from app.services.document_splitter import SplitResult, SplitPage
    from app.services.blob_storage import BlobStorageClient, BlobStorageError
    from app.utils.blob_path_helper import resolve_blob_path
    
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Validate prerequisites
    if document.split_status != 'DONE':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document must be split before OCR can be triggered. Current split_status: {document.split_status}"
        )
    
    if not document.pages_metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pages metadata not available. Document may not have been split yet."
        )
    
    # Concurrency guard: Check if OCR is already in progress
    if document.ocr_status == 'IN_PROGRESS':
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OCR is already running for this document. Please wait for it to complete."
        )
    
    # Check if OCR is already completed - skip unnecessary work
    if document.ocr_status == 'DONE':
        # OCR already completed, return success without processing
        fields_count = 0
        if document.extracted_fields and isinstance(document.extracted_fields, dict):
            fields_dict = document.extracted_fields.get('fields', {})
            if isinstance(fields_dict, dict):
                fields_count = len(fields_dict)
        
        return ApiResponse(
            success=True,
            message="OCR already completed for this document",
            data={
                "document_id": doc_id,
                "ocr_status": document.ocr_status,
                "coversheet_page_number": document.coversheet_page_number,
                "part_type": document.part_type,
                "fields_count": fields_count,
                "note": "OCR was already completed - no processing performed"
            }
        )
    
    # Check if OCR service is configured
    if not settings.ocr_base_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OCR service not configured (OCR_BASE_URL not set)"
        )
    
    # Check channel type - OCR should only run for ESMD/Fax, not Portal
    # Portal documents don't need OCR (they come pre-filled)
    from app.models.channel_type import ChannelType
    if packet.channel_type_id == ChannelType.GENZEON_PORTAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OCR is not applicable for Portal channel documents"
        )
    
    # Note: _process_ocr() will set ocr_status = 'IN_PROGRESS' internally, so we don't set it here
    
    # Get blob paths from metadata
    page_blob_paths = get_page_blob_paths_from_metadata(document)
    if not page_blob_paths:
        document.ocr_status = 'FAILED'
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No page blob paths found in pages_metadata"
        )
    
    # Initialize blob client
    container_name = settings.azure_storage_dest_container
    if not container_name:
        document.ocr_status = 'FAILED'
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Azure storage DEST container not configured"
        )
    
    blob_client = BlobStorageClient(
        storage_account_url=settings.storage_account_url,
        container_name=container_name,
        connection_string=settings.azure_storage_connection_string
    )
    
    # Create temp directory
    temp_dir = Path(tempfile.gettempdir()) / "service_ops_ocr_trigger"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_files_to_cleanup = []
    
    try:
        # Download each page from blob storage
        split_pages = []
        processing_root_path = None
        
        for page_num, blob_path in sorted(page_blob_paths.items()):
            # Normalize blob path - remove leading slashes and any existing prefix
            normalized_blob_path = blob_path.lstrip('/')
            if normalized_blob_path.startswith('service_ops_processing/'):
                normalized_blob_path = normalized_blob_path[len('service_ops_processing/'):]
            elif normalized_blob_path.startswith('service-ops-processing/'):
                normalized_blob_path = normalized_blob_path[len('service-ops-processing/'):]
            
            # Resolve with prefix helper (will add prefix if configured)
            resolved_blob_path = resolve_blob_path(normalized_blob_path)
            
            # Extract processing root path from first page
            # Path format: service_ops_processing/YYYY/MM-DD/{decision_tracking_id}/packet_{id}_pages/page_XXXX.pdf
            # processing_path should be: service_ops_processing/YYYY/MM-DD/{decision_tracking_id}
            if processing_root_path is None:
                path_parts = resolved_blob_path.split('/')
                # Find index of "packet_" directory (contains packet_*_pages)
                packet_idx = next((i for i, part in enumerate(path_parts) if part.startswith('packet_')), None)
                if packet_idx is not None:
                    # Extract everything before "packet_*_pages" directory
                    processing_root_path = '/'.join(path_parts[:packet_idx])
                else:
                    # Fallback: remove last 2 parts (filename and page directory)
                    # This handles legacy paths or different structures
                    if len(path_parts) >= 2:
                        processing_root_path = '/'.join(path_parts[:-2])
                    elif len(path_parts) >= 1:
                        processing_root_path = '/'.join(path_parts[:-1])
                    else:
                        # Last resort: use document's processing_path if available
                        processing_root_path = document.processing_path or ""
            
            # Create temp file for this page
            temp_file = temp_dir / f"page_{page_num}_{uuid.uuid4().hex[:8]}.pdf"
            
            logger.info(f"Downloading page {page_num} from blob: resolved_path='{resolved_blob_path}'")
            
            try:
                # Download page to temp file
                blob_client.download_to_file(
                    blob_path=normalized_blob_path,  # Use normalized path (without prefix)
                    local_path=str(temp_file),
                    container_name=container_name,
                    timeout=300
                )
                
                # Get file size
                file_size = temp_file.stat().st_size
                
                # Optional: Calculate SHA256 hash for integrity verification
                sha256 = None
                try:
                    import hashlib
                    with open(temp_file, 'rb') as f:
                        sha256 = hashlib.sha256(f.read()).hexdigest()
                except Exception as e:
                    logger.debug(f"Failed to calculate SHA256 for page {page_num}: {e}")
                    # SHA256 is optional, continue without it
                
                # Create SplitPage object with all required fields
                split_page = SplitPage(
                    page_number=page_num,
                    local_path=str(temp_file),
                    dest_blob_path=resolved_blob_path,  # Use resolved path (with prefix if configured)
                    content_type="application/pdf",
                    file_size_bytes=file_size,
                    sha256=sha256  # Optional but recommended for integrity
                )
                split_pages.append(split_page)
                temp_files_to_cleanup.append(str(temp_file))
                
                logger.info(f"Downloaded page {page_num}: {file_size} bytes")
                
            except BlobStorageError as e:
                logger.error(f"Failed to download page {page_num} from blob storage: {e}", exc_info=True)
                document.ocr_status = 'FAILED'
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to download page {page_num} from blob storage: {str(e)}"
                )
        
        if not split_pages:
            document.ocr_status = 'FAILED'
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No pages were successfully downloaded"
            )
        
        # Create SplitResult from downloaded pages
        split_result = SplitResult(
            processing_path=processing_root_path or "",
            page_count=len(split_pages),
            pages=split_pages,
            local_paths=[page.local_path for page in split_pages]
        )
        
        logger.info(f"Created SplitResult with {len(split_pages)} pages for OCR processing")
        
        # Validate channel_type_id is set
        if not packet.channel_type_id:
            document.ocr_status = 'FAILED'
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Channel type not set for this packet"
            )
        
        # Initialize DocumentProcessor
        processor = DocumentProcessor(
            channel_type_id=packet.channel_type_id
        )
        
        # Verify OCR service is available (DocumentProcessor initializes it)
        if not processor.ocr_service:
            document.ocr_status = 'FAILED'
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OCR service not configured or unavailable"
            )
        
        # Run OCR processing
        logger.info(f"Starting OCR processing for document {doc_id}")
        try:
            processor._process_ocr(
                db=db,
                packet_document=document,
                split_result=split_result,
                temp_files_to_cleanup=temp_files_to_cleanup
            )
            
            # Commit transaction
            db.commit()
            db.refresh(document)
            
            logger.info(
                f"OCR processing completed successfully for document {doc_id}. "
                f"Status: {document.ocr_status}, Coversheet: {document.coversheet_page_number}, "
                f"Part Type: {document.part_type}"
            )
            
        except Exception as e:
            logger.error(f"OCR processing failed for document {doc_id}: {e}", exc_info=True)
            document.ocr_status = 'FAILED'
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OCR processing failed: {str(e)}"
            )
        
        # Calculate fields count
        fields_count = 0
        if document.extracted_fields and isinstance(document.extracted_fields, dict):
            fields_dict = document.extracted_fields.get('fields', {})
            if isinstance(fields_dict, dict):
                fields_count = len(fields_dict)
        
        # Return success response
        return ApiResponse(
            success=True,
            message="OCR processing completed successfully",
            data={
                "document_id": doc_id,
                "ocr_status": document.ocr_status,
                "coversheet_page_number": document.coversheet_page_number,
                "part_type": document.part_type,
                "fields_count": fields_count
            }
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error during OCR trigger for document {doc_id}: {e}", exc_info=True)
        document.ocr_status = 'FAILED'
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during OCR processing: {str(e)}"
        )
    finally:
        # Cleanup temp files
        for temp_file_path in temp_files_to_cleanup:
            try:
                Path(temp_file_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_file_path}: {e}")


@router.post("/{packet_id}/documents/{doc_id}/pages/{page_num}/mark-coversheet")
async def mark_page_as_coversheet(
    packet_id: str,
    doc_id: str,
    page_num: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Mark a specific page as the coversheet and re-run OCR on it.
    This allows users to correct coversheet detection errors.
    
    Flow:
    1. Download the specified page from blob storage
    2. Run OCR on that page
    3. Update coversheet_page_number in database
    4. Update extracted_fields with new OCR results
    5. Update pages_metadata to mark the new coversheet
    6. Re-classify part type based on new coversheet
    """
    import tempfile
    from pathlib import Path
    from app.services.ocr_service import OCRService, OCRServiceError
    from app.services.part_classifier import PartClassifier
    
    # Find packet
    packet = db.query(PacketDB).filter(PacketDB.external_id == packet_id).first()
    if not packet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Packet not found"
        )
    
    # Find document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id,
        PacketDocumentDB.external_id == doc_id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    # Get pages metadata
    if not document.pages_metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pages metadata not available. Document may not have been split yet."
        )
    
    pages = document.pages_metadata.get('pages', [])
    target_page = next((p for p in pages if p.get('page_number') == page_num), None)
    
    if not target_page:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Page {page_num} not found in document"
        )
    
    # Get blob path for the page
    blob_path = target_page.get('blob_path') or target_page.get('relative_path')
    if not blob_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Blob path not available for page {page_num}"
        )
    
    # Normalize blob path - remove leading slashes and any existing prefix
    blob_path = blob_path.lstrip('/')
    if blob_path.startswith('service_ops_processing/'):
        blob_path = blob_path[len('service_ops_processing/'):]
    elif blob_path.startswith('service-ops-processing/'):
        blob_path = blob_path[len('service-ops-processing/'):]
    
    # Resolve with prefix helper (will add prefix if configured)
    resolved_blob_path = resolve_blob_path(blob_path)
    
    # A) Concurrency guard: Check if OCR is already in progress
    if document.ocr_status == 'IN_PROGRESS':
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="OCR is already running for this document. Please wait for it to complete."
        )
    
    # B) Set OCR status to IN_PROGRESS
    document.ocr_status = 'IN_PROGRESS'
    db.flush()
    
    try:
        # Download the page from blob storage
        container_name = settings.azure_storage_dest_container
        if not container_name:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Azure storage DEST container not configured"
            )
        
        blob_client = BlobStorageClient(
            storage_account_url=settings.storage_account_url,
            container_name=container_name,
            connection_string=settings.azure_storage_connection_string
        )
        
        # Log blob access
        log_blob_access(
            container_name=container_name,
            resolved_blob_path=resolved_blob_path,
            packet_id=packet_id,
            doc_id=doc_id,
            page_num=page_num
        )
        
        # Create temp file for the page
        temp_dir = Path(tempfile.gettempdir()) / "service_ops_ocr"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / f"page_{page_num}_{uuid.uuid4().hex[:8]}.pdf"
        
        logger.info(f"Downloading page {page_num} from blob: resolved_path='{resolved_blob_path}'")
        # Use download_to_file method - it will use the helper via _get_blob_client
        blob_client.download_to_file(blob_path, str(temp_file), container_name=container_name)
        
        # Run OCR on the page
        if not settings.ocr_base_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OCR service not configured (OCR_BASE_URL not set)"
            )
        
        # Create OCR service with max 3 retries (same as main OCR processing)
        ocr_service = OCRService(max_retries=3)
        logger.info(f"Running OCR on page {page_num} (max 3 retries)")
        try:
            ocr_result = ocr_service.run_ocr_on_pdf(str(temp_file))
        except OCRServiceError as e:
            # OCR failed after 3 attempts - don't raise, handle gracefully
            logger.error(f"OCR failed for page {page_num} after 3 attempts: {e}")
            # Clean up temp file
            try:
                temp_file.unlink()
            except Exception:
                pass
            # Return error response - user can try again or enter manually
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OCR failed for page {page_num} after 3 attempts. Please try again or enter fields manually."
            )
        
        # Clean up temp file
        try:
            temp_file.unlink()
        except Exception as e:
            logger.warning(f"Failed to delete temp file {temp_file}: {e}")
        
        # E) Run OCR on the page (already done above)
        # H) Classify part type based on OCR result
        part_classifier = PartClassifier()
        part_type = part_classifier.classify_part_type({
            'fields': ocr_result.get('fields', {}),
            'coversheet_type': ocr_result.get('coversheet_type', ''),
            'doc_type': ocr_result.get('doc_type', ''),
        })
        
        # Build normalized OCR result structure (same format as extracted_fields baseline)
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Update coversheet_page_number
        old_coversheet_page = document.coversheet_page_number
        document.coversheet_page_number = page_num
        document.part_type = part_type
        
        # Build normalized payload (same structure as extracted_fields baseline)
        normalized_ocr_payload = {
            'fields': ocr_result.get('fields', {}),
            'coversheet_type': ocr_result.get('coversheet_type', ''),
            'doc_type': ocr_result.get('doc_type', ''),
            'overall_document_confidence': ocr_result.get('overall_document_confidence', 0.0),
            'duration_ms': ocr_result.get('duration_ms', 0),
            'page_number': page_num,
            'raw': ocr_result.get('raw', {}),
            'source': 'COVERSHEET_REOCR_REPLACE',
            'last_updated_at': now_iso,
            'last_updated_by': current_user.username,
        }
        
        # Compute changed_fields for history (compare previous updated_extracted_fields with new OCR)
        previous_fields = {}
        if document.updated_extracted_fields and isinstance(document.updated_extracted_fields, dict):
            prev_fields_dict = document.updated_extracted_fields.get('fields', {})
            for field_name, field_data in prev_fields_dict.items():
                if isinstance(field_data, dict):
                    previous_fields[field_name] = str(field_data.get('value', '')).strip()
                else:
                    previous_fields[field_name] = str(field_data).strip()
        
        changed_fields = {}
        new_fields = normalized_ocr_payload.get('fields', {})
        for field_name, field_data in new_fields.items():
            new_value = str(field_data.get('value', '') if isinstance(field_data, dict) else field_data).strip()
            old_value = previous_fields.get(field_name, '').strip()
            if old_value != new_value:
                changed_fields[field_name] = {
                    'old': old_value,
                    'new': new_value
                }
        
        # MERGE OCR results into updated_extracted_fields intelligently:
        # - Only fill empty fields (don't override user-entered values)
        # - DO NOT modify extracted_fields (it's immutable baseline)
        
        # Initialize updated_extracted_fields if missing
        if not document.updated_extracted_fields:
            document.updated_extracted_fields = {'fields': {}}
        
        if 'fields' not in document.updated_extracted_fields:
            document.updated_extracted_fields['fields'] = {}
        
        # Get current fields (may have user-entered values)
        current_fields = document.updated_extracted_fields.get('fields', {})
        new_ocr_fields = normalized_ocr_payload.get('fields', {})
        
        # Merge: OCR only fills empty fields, doesn't override user-entered values
        for field_name, ocr_field_data in new_ocr_fields.items():
            current_field_data = current_fields.get(field_name)
            current_value = ""
            
            if current_field_data:
                if isinstance(current_field_data, dict):
                    current_value = str(current_field_data.get('value', '')).strip()
                else:
                    current_value = str(current_field_data).strip()
            
            # Only use OCR value if current field is empty
            if not current_value or current_value == "":
                # Fill empty field with OCR value
                if isinstance(ocr_field_data, dict):
                    current_fields[field_name] = {
                        'value': ocr_field_data.get('value', ''),
                        'confidence': ocr_field_data.get('confidence', 0.0),
                        'field_type': ocr_field_data.get('field_type', 'STRING'),
                        'source': 'OCR_MANUAL_TRIGGER'  # Mark as from manual OCR trigger
                    }
                else:
                    current_fields[field_name] = {
                        'value': str(ocr_field_data),
                        'confidence': normalized_ocr_payload.get('overall_document_confidence', 0.0),
                        'field_type': 'STRING',
                        'source': 'OCR_MANUAL_TRIGGER'
                    }
            # Else: Keep user-entered value (don't override)
        
        # Update metadata (coversheet_type, doc_type, etc.) from OCR
        document.updated_extracted_fields.update({
            'fields': current_fields,
            'coversheet_type': normalized_ocr_payload.get('coversheet_type', ''),
            'doc_type': normalized_ocr_payload.get('doc_type', ''),
            'overall_document_confidence': normalized_ocr_payload.get('overall_document_confidence', 0.0),
            'duration_ms': normalized_ocr_payload.get('duration_ms', 0),
            'page_number': page_num,
            'raw': normalized_ocr_payload.get('raw', {}),
            'source': 'MIXED',  # Mixed: user-entered + OCR
            'last_updated_at': now_iso,
            'last_updated_by': current_user.username
        })
        
        flag_modified(document, 'updated_extracted_fields')
        
        # Recompute changed_fields after merge (only fields that actually changed)
        changed_fields_after_merge = {}
        for field_name, field_data in current_fields.items():
            new_value = str(field_data.get('value', '') if isinstance(field_data, dict) else field_data).strip()
            old_value = previous_fields.get(field_name, '').strip()
            if old_value != new_value:
                changed_fields_after_merge[field_name] = {
                    'old': old_value,
                    'new': new_value
                }
        
        logger.info(
            f"Merged OCR results into updated_extracted_fields (working view) from page {page_num}. "
            f"Filled empty fields, preserved user-entered values. {len(changed_fields_after_merge)} field(s) changed. "
            f"Preserved extracted_fields (baseline unchanged)."
        )
        
        # Append history entry
        if not document.extracted_fields_update_history:
            document.extracted_fields_update_history = []
        
        history_entry = {
            'type': 'COVERSHEET_REOCR_MERGE',
            'updated_at': now_iso,
            'updated_by': current_user.username,
            'coversheet_page_number': page_num,
            'changed_fields': changed_fields_after_merge,
            'note': f'Re-ran OCR on page {page_num} and merged into working fields (filled empty fields, preserved user values)'
        }
        document.extracted_fields_update_history.append(history_entry)
        flag_modified(document, 'extracted_fields_update_history')
        
        # F) Update pages_metadata to mark the new coversheet and unmark the old one, and update OCR confidence
        if document.pages_metadata:
            pages = document.pages_metadata.get('pages', [])
            for page_meta in pages:
                if page_meta.get('page_number') == page_num:
                    page_meta['is_coversheet'] = True
                    # Update OCR confidence for this page from OCR result
                    page_meta['ocr_confidence'] = ocr_result.get('overall_document_confidence', 0.0)
                elif page_meta.get('page_number') == old_coversheet_page:
                    page_meta['is_coversheet'] = False
            flag_modified(document, 'pages_metadata')  # CRITICAL: Flag JSONB column as modified (nested dict modified)
        
        # I) Update OCR metadata - update/replace entry for this page only, keep others unchanged
        if not document.ocr_metadata:
            document.ocr_metadata = {}
        
        # Ensure 'pages' array exists
        if 'pages' not in document.ocr_metadata:
            document.ocr_metadata['pages'] = []
        
        # Find and update the page entry in OCR metadata (or append if not found)
        page_found = False
        for page_entry in document.ocr_metadata.get('pages', []):
            if page_entry.get('page_number') == page_num:
                # Update existing entry for this page
                page_entry.update({
                    'fields': ocr_result.get('fields', {}),
                    'duration_ms': ocr_result.get('duration_ms', 0),
                    'overall_document_confidence': ocr_result.get('overall_document_confidence', 0.0),
                    'coversheet_type': ocr_result.get('coversheet_type', ''),
                    'doc_type': ocr_result.get('doc_type', ''),
                })
                page_found = True
                break
        
        if not page_found:
            # Append new entry for this page
            document.ocr_metadata['pages'].append({
                'page_number': page_num,
                'fields': ocr_result.get('fields', {}),
                'duration_ms': ocr_result.get('duration_ms', 0),
                'overall_document_confidence': ocr_result.get('overall_document_confidence', 0.0),
                'coversheet_type': ocr_result.get('coversheet_type', ''),
                'doc_type': ocr_result.get('doc_type', ''),
            })
        
        # Update top-level OCR metadata fields
        document.ocr_metadata['coversheet_page_number'] = page_num
        document.ocr_metadata['part_type'] = part_type
        document.ocr_metadata['manually_set'] = True
        document.ocr_metadata['set_by'] = current_user.username
        document.ocr_metadata['set_at'] = now_iso
        flag_modified(document, 'ocr_metadata')  # CRITICAL: Flag JSONB column as modified (nested dict modified)
        
        # Mark OCR as done
        document.ocr_status = 'DONE'
        document.updated_at = datetime.now(timezone.utc)
        
        # Skip packet table sync (JSON-only flow per requirements)
        
        # Commit and return updated document DTO
        try:
            db.commit()
            db.refresh(document)
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to commit mark coversheet changes: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save changes: {str(e)}"
            )
        
        # Convert to DTO for response
        try:
            document_dto = document_to_dto(document, packet_id, db)
            # Handle both Pydantic v1 (.dict()) and v2 (.model_dump())
            if hasattr(document_dto, 'model_dump'):
                document_dict = document_dto.model_dump()
            else:
                document_dict = document_dto.dict()
            
            logger.info(
                f"Document DTO after mark coversheet - updatedExtractedFields fields count: "
                f"{len(document_dict.get('updatedExtractedFields', {}).get('fields', {})) if document_dict.get('updatedExtractedFields') else 0}"
            )
        except Exception as dto_error:
            logger.error(
                f"Failed to convert document to DTO after marking coversheet: {dto_error}",
                exc_info=True
            )
            # Return response without document DTO (UI will need to refetch)
            return ApiResponse(
                success=True,
                data={
                    'message': f'Page {page_num} marked as coversheet and OCR completed',
                    'coversheetPageNumber': page_num,
                    'partType': part_type,
                    'fieldsExtracted': len(ocr_result.get('fields', {})),
                    'confidence': ocr_result.get('overall_document_confidence', 0.0),
                    'document': None,  # DTO conversion failed, UI should refetch
                    'warning': f'Document DTO conversion failed: {str(dto_error)}'
                },
                message=f"Page {page_num} successfully marked as coversheet (note: document DTO conversion failed)"
            )
        
        logger.info(
            f"Successfully marked page {page_num} as coversheet for document {doc_id}. "
            f"Previous coversheet was page {old_coversheet_page}. Part type: {part_type}. "
            f"Replaced updated_extracted_fields with new OCR result."
        )
        
        return ApiResponse(
            success=True,
            data={
                'message': f'Page {page_num} marked as coversheet and OCR completed',
                'coversheetPageNumber': page_num,
                'partType': part_type,
                'fieldsExtracted': len(ocr_result.get('fields', {})),
                'confidence': ocr_result.get('overall_document_confidence', 0.0),
                'document': document_dict,  # Return full document DTO so UI can update immediately
            },
            message=f"Page {page_num} successfully marked as coversheet"
        )
        
    except OCRServiceError as e:
        logger.error(f"OCR failed for page {page_num}: {e}", exc_info=True)
        document.ocr_status = 'FAILED'
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OCR processing failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to mark page {page_num} as coversheet: {e}", exc_info=True)
        document.ocr_status = 'FAILED'
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process page: {str(e)}"
        )

