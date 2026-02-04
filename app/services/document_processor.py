"""
Document Processor Service
Orchestrates the end-to-end document processing pipeline:
1. Parse payload
2. Download documents from blob storage
3. Split documents into per-page PDFs
4. Upload split pages to blob storage
5. Persist packet and packet_document records to database
"""
import logging
import uuid
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from app.services.db import get_db_session
from app.services.payload_parser import PayloadParser
from app.services.document_splitter import DocumentSplitter, DocumentSplitError, SplitResult
from app.services.blob_storage import BlobStorageClient, BlobStorageError
from app.services.ocr_service import OCRService, OCRServiceError
from app.services.coversheet_detector import CoversheetDetector
from app.services.part_classifier import PartClassifier
from app.services.pdf_merger import PDFMerger, PDFMergeError
from app.services.document_processor_resume import check_resume_state, ResumeState, get_page_blob_paths_from_metadata
from app.services.channel_processing_strategy import get_channel_strategy, ChannelProcessingStrategy
from app.models.channel_type import ChannelType
from app.utils.path_builder import build_consolidated_paths, build_page_blob_path
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.config import settings

logger = logging.getLogger(__name__)


class DocumentProcessorError(Exception):
    """Custom exception for document processing operations"""
    pass


class DocumentProcessor:
    """
    Orchestrates document processing pipeline from message to database.
    
    CONSOLIDATED WORKFLOW (Current Implementation):
    Even if the payload contains multiple documents, they are merged into ONE consolidated PDF
    and treated as a single document for the packet. This ensures:
    - 1 Packet (decision_tracking_id) -> EXACTLY ONE PacketDocument
    - All input documents are merged in order into a single consolidated PDF
    - The consolidated PDF is split into pages for OCR processing
    - Storage uses date-partitioned structure: service_ops_processing/YYYY/MM-DD/{decision_tracking_id}/
    
    Flow:
    1. Parse payload to get normalized document list
    2. Get or create packet by decision_tracking_id (idempotent)
    3. Get or create single packet_document for this packet (enforced: ONE per packet_id)
    4. Download ALL payload documents from SOURCE container
    5. Merge all documents into ONE consolidated PDF (in order)
    6. Upload consolidated PDF to DEST container (date-partitioned path)
    7. Split consolidated PDF into per-page PDFs
    8. Upload each page to DEST container (overwrite=True for REPLACE policy)
    9. Run OCR on all pages, detect coversheet, classify Part A/B
    10. Update packet_document with pages_metadata, ocr_metadata, extracted_fields
    11. Commit transaction, cleanup temp files
    
    REPLACE Policy (Idempotency):
    - If same decision_tracking_id is processed again, rebuild consolidated PDF from payload
    - Always overwrite consolidated PDF blob and page blobs (overwrite=True)
    - Always replace pages_metadata, ocr_metadata, extracted_fields with new results
    - Old page blobs not in new run are ignored (UI relies on pages_metadata)
    """
    
    def __init__(
        self,
        blob_client: Optional[BlobStorageClient] = None,
        splitter: Optional[DocumentSplitter] = None,
        temp_dir: Optional[str] = None,
        channel_type_id: Optional[int] = None
    ):
        """
        Initialize document processor.
        
        Args:
            blob_client: BlobStorageClient instance (creates new if None)
            splitter: DocumentSplitter instance (creates new if None)
            temp_dir: Temp directory for file operations (uses settings if None)
            channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD), optional for backward compatibility
        """
        # Initialize blob client (container_name not required at init since we use per-call containers)
        self.blob_client = blob_client or BlobStorageClient()
        self.splitter = splitter or DocumentSplitter(temp_dir=temp_dir or settings.blob_temp_dir)
        self.pdf_merger = PDFMerger(temp_dir=temp_dir or settings.blob_temp_dir)
        self.temp_dir = Path(temp_dir or settings.blob_temp_dir)
        
        # Initialize OCR service and helpers (only if OCR service is configured)
        if settings.ocr_base_url and settings.ocr_base_url.strip():
            try:
                self.ocr_service = OCRService()
                self.coversheet_detector = CoversheetDetector()
                self.part_classifier = PartClassifier()
            except Exception as e:
                # If OCR service initialization fails, disable OCR
                logger.warning(f"OCR service initialization failed: {e}, OCR processing will be disabled")
                self.ocr_service = None
                self.coversheet_detector = None
                self.part_classifier = None
        else:
            # OCR not configured - disable OCR processing
            self.ocr_service = None
            self.coversheet_detector = None
            self.part_classifier = None
        
        # Initialize channel strategy
        self.channel_type_id = channel_type_id
        self.channel_strategy = get_channel_strategy(channel_type_id)
        if channel_type_id:
            logger.info(f"DocumentProcessor initialized with channel_type_id={channel_type_id}")
        else:
            logger.info("DocumentProcessor initialized without channel_type_id (backward compatibility mode)")
        
        # Validate SOURCE and DEST container settings (lazy validation when actually used)
        try:
            settings.validate_storage_containers()
        except ValueError as e:
            raise DocumentProcessorError(str(e)) from e
        
        source_container = settings.azure_storage_source_container or settings.container_name
        logger.info(
            f"DocumentProcessor initialized: SOURCE container='{source_container}', "
            f"DEST container='{settings.azure_storage_dest_container}'"
        )
    
    def process_message(
        self,
        message: SendServiceOpsDB,
        inbox_id: Optional[int] = None
    ) -> None:
        """
        Process a single message through the complete pipeline.
        
        Args:
            message: SendServiceOpsDB message from integration.send_serviceops
            inbox_id: Optional inbox_id for tracking
            
        Raises:
            DocumentProcessorError: If processing fails at any stage
        """
        logger.info(
            f"Starting document processing: message_id={message.message_id}, inbox_id={inbox_id}"
        )
        
        # Initialize temp files cleanup list early to ensure it always exists in exception handler
        # This prevents NameError if exception occurs before line 212 (old initialization location)
        temp_files_to_cleanup = []
        logger.debug(
            f"Initialized temp_files_to_cleanup list for message_id={message.message_id}, "
            f"inbox_id={inbox_id}"
        )
        
        # Step 1: Parse payload
        if not message.payload:
            raise DocumentProcessorError(f"Message {message.message_id} has no payload")
        
        try:
            parsed = PayloadParser.parse_full_payload(message.payload)
            logger.info(
                f"Payload validation successful for message {message.message_id}: "
                f"decision_tracking_id={parsed.decision_tracking_id}, "
                f"unique_id={parsed.unique_id}, documents={len(parsed.documents)}"
            )
        except ValueError as e:
            logger.error(
                f"Payload validation failed for message {message.message_id}: {e}",
                exc_info=True
            )
            raise DocumentProcessorError(f"Payload validation failed: {e}") from e
        
        # Check if documents are missing or empty
        has_documents = parsed.documents and len(parsed.documents) > 0
        
        logger.info(
            f"Parsed payload: decision_tracking_id={parsed.decision_tracking_id}, "
            f"unique_id={parsed.unique_id}, documents={len(parsed.documents) if parsed.documents else 0}, "
            f"has_documents={has_documents}"
        )
        
        # If no documents, create packet with empty document state and return early
        if not has_documents:
            logger.warning(
                f"Message {message.message_id} has no documents or empty documents array. "
                f"Will create packet with empty document state."
            )
            with get_db_session() as db:
                try:
                    # Extract submission date
                    extracted_submission_date = self._extract_submission_date_from_payload(
                        payload=message.payload if hasattr(message, 'payload') else {},
                        parsed=parsed,
                        channel_type_id=getattr(message, 'channel_type_id', None) or self.channel_type_id
                    )
                    
                    # Use extracted submission date if found, otherwise fallback to message.created_at
                    if extracted_submission_date:
                        message_received_date = extracted_submission_date
                    else:
                        message_received_date = message.created_at if message.created_at else datetime.now(timezone.utc)
                        # Normalize to midnight for consistency
                        message_received_date = datetime(
                            year=message_received_date.year,
                            month=message_received_date.month,
                            day=message_received_date.day,
                            hour=0,
                            minute=0,
                            second=0,
                            microsecond=0,
                            tzinfo=timezone.utc
                        )
                    
                    # Get or create packet
                    packet = self._get_or_create_packet(
                        db=db,
                        decision_tracking_id=parsed.decision_tracking_id,
                        unique_id=parsed.unique_id,
                        esmd_transaction_id=parsed.esmd_transaction_id,
                        received_date=message_received_date,
                        channel_type_id=getattr(message, 'channel_type_id', None) or self.channel_type_id,
                        payload=message.payload if hasattr(message, 'payload') else {}
                    )
                    
                    # Create empty document state
                    packet_document = self._get_or_create_empty_document(
                        db=db,
                        packet=packet,
                        message=message
                    )
                    
                    # CRITICAL FIX: For Portal channel, even if documents array is empty,
                    # we should extract fields from payload.ocr.fields if available
                    # This allows UI to display packet data even without document files
                    current_channel_type_id = getattr(message, 'channel_type_id', None) or self.channel_type_id
                    payload = message.payload if hasattr(message, 'payload') else {}
                    
                    if (current_channel_type_id == ChannelType.GENZEON_PORTAL and 
                        payload and 
                        isinstance(payload, dict) and 
                        payload.get('ocr') and 
                        payload['ocr'].get('fields')):
                        
                        logger.info(
                            f"Portal channel with empty documents but OCR fields present. "
                            f"Extracting fields from payload.ocr for packet {packet.external_id}"
                        )
                        
                        try:
                            # Create minimal SplitResult for Portal (no pages needed)
                            from app.services.document_splitter import SplitResult, SplitPage
                            empty_split_result = SplitResult(
                                processing_path="",
                                page_count=0,
                                pages=[],
                                local_paths=[]
                            )
                            
                            # Process Portal fields from payload
                            self._process_portal_fields_from_payload(
                                db=db,
                                packet_document=packet_document,
                                split_result=empty_split_result,
                                payload=payload
                            )
                            
                            # Commit the OCR field extraction
                            db.commit()
                            logger.info(
                                f"✓ Portal fields extracted and saved for packet {packet.external_id} "
                                f"(packet_document_id={packet_document.packet_document_id})"
                            )
                        except Exception as portal_error:
                            logger.error(
                                f"Failed to extract Portal fields from payload.ocr: {portal_error}",
                                exc_info=True
                            )
                            # Rollback and continue - packet created but fields not extracted
                            db.rollback()
                            # Re-commit just the packet/document creation
                            db.commit()
                    else:
                        # Not Portal or no OCR fields - just commit empty document state
                        db.commit()
                        logger.info(
                            f"✓ Created packet {packet.external_id} with empty document state: "
                            f"packet_document_id={packet_document.packet_document_id}"
                        )
                    
                    return  # Skip all document processing steps
                except Exception as e:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise DocumentProcessorError(f"Failed to create empty document state: {e}") from e
        
        # Check for resume state (using existing DB fields as checkpoints)
        resume_state = None
        with get_db_session() as db:
            resume_state = check_resume_state(db, parsed.decision_tracking_id)
        
        # If already fully processed, return early
        if resume_state and not resume_state.can_resume:
            logger.info(
                f"Document already fully processed: packet_id={resume_state.packet.packet_id}, "
                f"packet_document_id={resume_state.packet_document.packet_document_id}"
            )
            return
        
        # Process with step commits and resume logic
        self._process_with_step_commits(
            message=message,
            parsed=parsed,
            inbox_id=inbox_id,
            resume_state=resume_state,
            temp_files_to_cleanup=temp_files_to_cleanup
        )
    
    def _process_with_step_commits(
        self,
        message: SendServiceOpsDB,
        parsed,
        inbox_id: Optional[int],
        resume_state: Optional[ResumeState],
        temp_files_to_cleanup: list
    ) -> None:
        """
        Process message with step commits and resume logic.
        
        Step commits:
        - Transaction A: Parse, get-or-create packet/document, commit
        - External: Download, merge, upload consolidated PDF
        - Transaction B: Update consolidated blob path, commit
        - External: Split, upload pages
        - Transaction C: Update pages_metadata, split_status, commit
        - External: Run OCR
        - Transaction D: Update ocr_metadata, extracted_fields, ocr_status, commit
        
        Resume logic:
        - If resume_state.resume_from == 'ocr': Skip to OCR
        - If resume_state.resume_from == 'split': Skip to split
        - If resume_state.resume_from == 'merge': Skip to merge
        - Otherwise: Start from beginning
        """
        # Determine where to start based on resume state
        start_from = 'beginning'
        packet = None
        packet_document = None
        
        if resume_state and resume_state.can_resume:
            start_from = resume_state.resume_from
            packet = resume_state.packet
            packet_document = resume_state.packet_document
            logger.info(
                f"Resuming from {start_from}: packet_id={packet.packet_id}, "
                f"packet_document_id={packet_document.packet_document_id}"
            )
        
        # Get channel_type_id from message if not already set (fallback)
        # Default to ESMD (3) if NULL or empty
        message_channel_type_id = getattr(message, 'channel_type_id', None)
        if message_channel_type_id is None or message_channel_type_id == 0:
            message_channel_type_id = ChannelType.ESMD  # Default to ESMD
            logger.debug(f"channel_type_id is NULL/empty, defaulting to ESMD (3)")
        
        if message_channel_type_id and message_channel_type_id != self.channel_type_id:
            # Update strategy if channel_type_id changed
            self.channel_type_id = message_channel_type_id
            self.channel_strategy = get_channel_strategy(message_channel_type_id)
            logger.info(f"Updated channel strategy: channel_type_id={message_channel_type_id}")
        elif not self.channel_type_id or self.channel_type_id == 0:
            # Use message channel_type_id if processor doesn't have one (or is 0)
            self.channel_type_id = message_channel_type_id
            self.channel_strategy = get_channel_strategy(message_channel_type_id)
        
        # Transaction A: Get or create packet and document (if not resuming)
        if start_from == 'beginning' or start_from == 'merge':
            with get_db_session() as db:
                try:
                    # Step 2: Extract submission date from payload (preserves original timestamp)
                    # This is the ONLY extraction point - no updates after this
                    # Store raw timestamp - normalization happens only for SLA/due date calculations
                    extracted_submission_date = self._extract_submission_date_from_payload(
                        payload=message.payload if hasattr(message, 'payload') else {},
                        parsed=parsed,
                        channel_type_id=self.channel_type_id
                    )
                    
                    # Use extracted submission date if found, otherwise fallback to message.created_at
                    # (fallback is only for database constraint - received_date is NOT NULL)
                    if extracted_submission_date:
                        message_received_date = extracted_submission_date
                        logger.info(
                            f"Extracted submission date from payload (raw timestamp): {extracted_submission_date} "
                            f"(channel_type_id={self.channel_type_id})"
                        )
                    else:
                        # Fallback to message.created_at (required for database NOT NULL constraint)
                        # Store raw timestamp (no normalization)
                        message_received_date = message.created_at if message.created_at else datetime.now(timezone.utc)
                        # Ensure timezone-aware
                        if message_received_date.tzinfo is None:
                            message_received_date = message_received_date.replace(tzinfo=timezone.utc)
                        logger.info(
                            f"Submission date not found in payload, using message.created_at (raw timestamp): "
                            f"{message_received_date} (channel_type_id={self.channel_type_id})"
                        )
                    
                    packet = self._get_or_create_packet(
                        db=db,
                        decision_tracking_id=parsed.decision_tracking_id,
                        unique_id=parsed.unique_id,
                        esmd_transaction_id=parsed.esmd_transaction_id,
                        received_date=message_received_date,
                        channel_type_id=self.channel_type_id,  # Pass channel_type_id
                        payload=message.payload if hasattr(message, 'payload') else {}  # Pass payload for packet_id extraction
                    )
                    
                    logger.info(
                        f"Using packet: packet_id={packet.packet_id}, external_id={packet.external_id}, "
                        f"decision_tracking_id={parsed.decision_tracking_id}"
                    )
                    
                    # Step 3: Get or create consolidated packet_document
                    packet_document = self._get_or_create_consolidated_document(
                        db=db,
                        packet_id=packet.packet_id
                    )
                    
                    # If document exists, we'll rebuild it (REPLACE policy)
                    is_rebuild = packet_document.packet_document_id is not None
                    if is_rebuild:
                        logger.info(
                            f"Found existing consolidated document (packet_document_id={packet_document.packet_document_id}), "
                            f"will rebuild with new payload (REPLACE policy)"
                        )
                        # Reset statuses for rebuild (REPLACE policy)
                        packet_document.split_status = 'NOT_STARTED'
                        packet_document.ocr_status = 'NOT_STARTED'
                        packet_document.updated_at = datetime.now(timezone.utc)
                    else:
                        db.add(packet_document)
                        db.flush()  # Get packet_document_id
                        logger.info(
                            f"Created new consolidated document: packet_document_id={packet_document.packet_document_id}, "
                            f"external_id={packet_document.external_id}"
                        )
                    
                    # Commit Transaction A
                    db.commit()
                    logger.info(
                        f"✓ Transaction A committed: packet_id={packet.packet_id}, "
                        f"packet_document_id={packet_document.packet_document_id}"
                    )
                except Exception as e:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise DocumentProcessorError(f"Failed to create packet/document: {e}") from e
                
        # External Work: Download, merge, upload consolidated PDF (skip if resuming from split/ocr)
        # Note: Empty documents are handled earlier in process_message(), so we only reach here if has_documents=True
        consolidated_pdf_path = None
        consolidated_file_size = 0
        paths = None
        
        if start_from == 'beginning' or start_from == 'merge':
            # Step 4: Deduplicate documents by source_absolute_url before downloading
            # This prevents duplicate pages when payload lists the same blob URL multiple times
            docs_to_merge = []
            seen_urls = set()
            duplicate_count = 0
            
            for doc in parsed.documents:
                if doc.source_absolute_url in seen_urls:
                    duplicate_count += 1
                    logger.info(
                        f"Skipping duplicate document URL: {doc.source_absolute_url} "
                        f"(file_name: {doc.file_name})"
                    )
                else:
                    seen_urls.add(doc.source_absolute_url)
                    docs_to_merge.append(doc)
            
            if duplicate_count > 0:
                logger.info(
                    f"Deduplicated documents by URL: {len(parsed.documents)} -> {len(docs_to_merge)} "
                    f"({duplicate_count} duplicate(s) removed)"
                )
            
            # Step 4: Download deduplicated documents from SOURCE container
            downloaded_docs = []
            source_container = settings.azure_storage_source_container or settings.container_name
            
            logger.info(f"Downloading {len(docs_to_merge)} unique documents from SOURCE container for merging")
            for doc_idx, doc in enumerate(docs_to_merge, 1):
                logger.info(
                    f"Downloading document {doc_idx}/{len(docs_to_merge)}: "
                    f"{doc.file_name} (source: {doc.source_absolute_url})"
                )
                try:
                    download_result = self.blob_client.download_to_temp(
                        blob_path_or_url=doc.source_absolute_url,
                        subdir=f"consolidated/{parsed.unique_id}",
                        container_name=source_container,
                        timeout=300
                    )
                    downloaded_docs.append({
                        'local_path': download_result['local_path'],
                        'mime_type': doc.mime_type,
                        'file_name': doc.file_name,
                        'file_size': download_result['size_bytes']
                    })
                    temp_files_to_cleanup.append(download_result['local_path'])
                    logger.info(
                        f"Downloaded: {doc.file_name} -> {download_result['local_path']} "
                        f"({download_result['size_bytes']} bytes)"
                    )
                except BlobStorageError as e:
                    logger.error(f"Failed to download document {doc.file_name}: {e}", exc_info=True)
                    raise DocumentProcessorError(f"Failed to download document {doc.file_name}: {e}") from e
            
            if not downloaded_docs:
                raise DocumentProcessorError("No documents downloaded for merging")
            
            # Step 5: Merge all documents into ONE consolidated PDF
            logger.info(f"Merging {len(downloaded_docs)} documents into consolidated PDF")
            consolidated_pdf_path = self.temp_dir / f"consolidated_{parsed.unique_id}_{packet.packet_id}.pdf"
            consolidated_pdf_path.parent.mkdir(parents=True, exist_ok=True)
            temp_files_to_cleanup.append(str(consolidated_pdf_path))
            
            try:
                total_pages_before_split = self.pdf_merger.merge_documents(
                    input_paths=[d['local_path'] for d in downloaded_docs],
                    mime_types=[d['mime_type'] for d in downloaded_docs],
                    output_path=str(consolidated_pdf_path)
                )
                consolidated_file_size = consolidated_pdf_path.stat().st_size
                logger.info(
                    f"Merged {len(downloaded_docs)} documents into consolidated PDF: "
                    f"{consolidated_pdf_path} ({consolidated_file_size} bytes, {total_pages_before_split} pages)"
                )
            except PDFMergeError as e:
                logger.error(f"Failed to merge documents: {e}", exc_info=True)
                raise DocumentProcessorError(f"Failed to merge documents: {e}") from e
            
            # Step 6: Build blob paths
            dt_utc = message.created_at if hasattr(message, 'created_at') and message.created_at else datetime.now(timezone.utc)
            paths = build_consolidated_paths(
                decision_tracking_id=parsed.decision_tracking_id,
                packet_id=packet.packet_id,
                dt_utc=dt_utc
            )
            
            logger.info(
                f"Built blob paths: processing_root={paths.processing_root_path}, "
                f"consolidated_pdf={paths.consolidated_pdf_blob_path}"
            )
            
            # Step 7: Upload consolidated PDF to DEST container
            dest_container = settings.azure_storage_dest_container
            logger.info(
                f"Uploading consolidated PDF to DEST container '{dest_container}': {paths.consolidated_pdf_blob_path}"
            )
            try:
                consolidated_upload_result = self.blob_client.upload_file(
                    local_path=str(consolidated_pdf_path),
                    dest_blob_path=paths.consolidated_pdf_blob_path,
                    container_name=dest_container,
                    content_type='application/pdf',
                    overwrite=True  # REPLACE policy
                )
                logger.info(
                    f"Uploaded consolidated PDF: {consolidated_upload_result['size_bytes']} bytes, "
                    f"blob_url={consolidated_upload_result['blob_url']}"
                )
            except BlobStorageError as e:
                logger.error(f"Failed to upload consolidated PDF: {e}", exc_info=True)
                raise DocumentProcessorError(f"Failed to upload consolidated PDF: {e}") from e
            
            # Transaction B: Update consolidated blob path
            with get_db_session() as db:
                try:
                    # Reload packet_document
                    packet_document = db.query(PacketDocumentDB).filter(
                        PacketDocumentDB.packet_document_id == packet_document.packet_document_id
                    ).first()
                    
                    # Update with consolidated blob path
                    packet_document.consolidated_blob_path = paths.consolidated_pdf_blob_path
                    # Use the actual blob filename (packet_{packet_id}.pdf) instead of hardcoded "consolidated.pdf"
                    blob_filename = Path(paths.consolidated_pdf_blob_path).name  # e.g., "packet_12345.pdf"
                    packet_document.file_name = blob_filename
                    packet_document.file_size = self._format_file_size(consolidated_file_size)
                    packet_document.processing_path = paths.processing_root_path
                    packet_document.updated_at = datetime.now(timezone.utc)
                    
                    db.commit()
                    logger.info(
                        f"✓ Transaction B committed: consolidated_blob_path={paths.consolidated_pdf_blob_path}"
                    )
                except Exception as e:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise DocumentProcessorError(f"Failed to update consolidated blob path: {e}") from e
        else:
            # Resuming from split/ocr - get paths from existing document
            with get_db_session() as db:
                packet_document_db = db.query(PacketDocumentDB).filter(
                    PacketDocumentDB.packet_document_id == packet_document.packet_document_id
                ).first()
                if packet_document_db.consolidated_blob_path:
                    # Rebuild paths from existing data
                    dt_utc = message.created_at if hasattr(message, 'created_at') and message.created_at else datetime.now(timezone.utc)
                    paths = build_consolidated_paths(
                        decision_tracking_id=parsed.decision_tracking_id,
                        packet_id=packet.packet_id,
                        dt_utc=dt_utc
                    )
                    logger.info(f"Resuming: using existing consolidated_blob_path={packet_document_db.consolidated_blob_path}")
                else:
                    raise DocumentProcessorError("Cannot resume: consolidated_blob_path not found")
                
        # External Work: Split and upload pages (skip if resuming from OCR)
        split_result = None
        
        if start_from == 'beginning' or start_from == 'merge' or start_from == 'split':
            # Download consolidated PDF if resuming from split
            if start_from == 'split':
                # Reload packet_document to get consolidated_blob_path
                with get_db_session() as db:
                    packet_document_db = db.query(PacketDocumentDB).filter(
                        PacketDocumentDB.packet_document_id == packet_document.packet_document_id
                    ).first()
                    if packet_document_db and packet_document_db.consolidated_blob_path:
                        logger.info(f"Resuming from split: downloading consolidated PDF from {packet_document_db.consolidated_blob_path}")
                        dest_container = settings.azure_storage_dest_container
                        consolidated_pdf_path = self.temp_dir / f"consolidated_resume_{packet.packet_id}.pdf"
                        consolidated_pdf_path.parent.mkdir(parents=True, exist_ok=True)
                        temp_files_to_cleanup.append(str(consolidated_pdf_path))
                        
                        try:
                            self.blob_client.download_to_file(
                                blob_path_or_url=packet_document_db.consolidated_blob_path,
                                local_path=str(consolidated_pdf_path),
                                container_name=dest_container
                            )
                            consolidated_file_size = consolidated_pdf_path.stat().st_size
                            logger.info(f"Downloaded consolidated PDF: {consolidated_file_size} bytes")
                        except BlobStorageError as e:
                            logger.error(f"Failed to download consolidated PDF: {e}", exc_info=True)
                            raise DocumentProcessorError(f"Failed to download consolidated PDF: {e}") from e
                    else:
                        raise DocumentProcessorError("Cannot resume from split: consolidated_blob_path not found")
            
            # Step 8: Split consolidated PDF into per-page PDFs
            logger.info(f"Splitting consolidated PDF into pages")
            try:
                split_result = self.splitter.split_document(
                    input_path=str(consolidated_pdf_path),
                    unique_id=parsed.unique_id,
                    document_unique_identifier="CONSOLIDATED",
                    original_file_name="consolidated.pdf",
                    mime_type="application/pdf"
                )
                logger.info(f"Split complete: {split_result.page_count} pages")
            except DocumentSplitError as e:
                logger.error(f"Failed to split consolidated PDF: {e}", exc_info=True)
                raise DocumentProcessorError(f"Failed to split consolidated PDF: {e}") from e
            
            # Step 9: Upload each page to DEST container
            dest_container = settings.azure_storage_dest_container
            logger.info(f"Uploading {split_result.page_count} pages to DEST container")
            page_metadata_list = []
            for page in split_result.pages:
                page_blob_path = build_page_blob_path(
                    pages_folder_blob_prefix=paths.pages_folder_blob_prefix,
                    packet_id=packet.packet_id,
                    page_number=page.page_number
                )
                
                logger.info(
                    f"Uploading page {page.page_number} to DEST container '{dest_container}': {page_blob_path}"
                )
                try:
                    upload_result = self.blob_client.upload_file(
                        local_path=page.local_path,
                        dest_blob_path=page_blob_path,
                        container_name=dest_container,
                        content_type=page.content_type,
                        overwrite=True  # REPLACE policy
                    )
                    temp_files_to_cleanup.append(page.local_path)
                    
                    page_metadata_list.append({
                        'page_number': page.page_number,
                        'blob_path': page_blob_path,
                        'relative_path': page_blob_path,
                        'content_type': page.content_type,
                        'file_size_bytes': page.file_size_bytes,
                        'sha256': page.sha256,
                        'is_coversheet': False,
                    })
                    
                    logger.info(f"Uploaded page {page.page_number}: {upload_result['size_bytes']} bytes")
                except BlobStorageError as e:
                    logger.error(f"Failed to upload page {page.page_number}: {e}", exc_info=True)
                    raise DocumentProcessorError(f"Failed to upload page {page.page_number}: {e}") from e
            
            # Transaction C: Update pages_metadata and split_status
            with get_db_session() as db:
                try:
                    # Reload packet_document
                    packet_document = db.query(PacketDocumentDB).filter(
                        PacketDocumentDB.packet_document_id == packet_document.packet_document_id
                    ).first()
                    
                    # Update with pages metadata
                    packet_document.page_count = split_result.page_count
                    packet_document.pages_metadata = {
                        'version': 'v1',
                        'pages': page_metadata_list
                    }
                    flag_modified(packet_document, 'pages_metadata')
                    packet_document.split_status = 'DONE'
                    packet_document.updated_at = datetime.now(timezone.utc)
                    
                    db.commit()
                    logger.info(
                        f"✓ Transaction C committed: split_status=DONE, pages={split_result.page_count}"
                    )
                except Exception as e:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise DocumentProcessorError(f"Failed to update pages metadata: {e}") from e
        else:
            # Resuming from OCR - download pages from blob storage
            logger.info("Resuming from OCR: downloading pages from blob storage")
            # Reload packet_document to get pages_metadata
            with get_db_session() as db:
                packet_document_db = db.query(PacketDocumentDB).filter(
                    PacketDocumentDB.packet_document_id == packet_document.packet_document_id
                ).first()
                if not packet_document_db:
                    raise DocumentProcessorError("Cannot resume from OCR: packet_document not found")
            
            page_blob_paths = get_page_blob_paths_from_metadata(packet_document_db)
            if not page_blob_paths:
                raise DocumentProcessorError("Cannot resume from OCR: pages_metadata not found")
            
            # Download pages from blob storage
            dest_container = settings.azure_storage_dest_container
            split_pages = []
            for page_num, blob_path in sorted(page_blob_paths.items()):
                local_page_path = self.temp_dir / f"resume_page_{packet.packet_id}_{page_num}.pdf"
                local_page_path.parent.mkdir(parents=True, exist_ok=True)
                temp_files_to_cleanup.append(str(local_page_path))
                
                try:
                    self.blob_client.download_to_file(
                        blob_path_or_url=blob_path,
                        local_path=str(local_page_path),
                        container_name=dest_container
                    )
                    
                    # Create SplitPage-like object
                    from app.services.document_splitter import SplitPage
                    split_pages.append(SplitPage(
                        page_number=page_num,
                        local_path=str(local_page_path),
                        dest_blob_path=blob_path,
                        content_type="application/pdf",
                        file_size_bytes=local_page_path.stat().st_size,
                        sha256=None  # Not needed for resume
                    ))
                    logger.info(f"Downloaded page {page_num} from {blob_path}")
                except BlobStorageError as e:
                    logger.error(f"Failed to download page {page_num} from {blob_path}: {e}", exc_info=True)
                    raise DocumentProcessorError(f"Failed to download page {page_num}: {e}") from e
            
            # Create SplitResult from downloaded pages
            split_result = SplitResult(
                processing_path=packet_document_db.processing_path or "",
                page_count=len(split_pages),
                pages=split_pages,
                local_paths=[p.local_path for p in split_pages]
            )
            logger.info(f"Resumed: downloaded {len(split_pages)} pages for OCR processing")
        
        # External Work: Run OCR OR Extract from Payload (channel-dependent)
        if start_from != 'ocr':
            # Check if channel strategy requires OCR
            if self.channel_strategy.should_run_ocr() and self.ocr_service:
                # ESMD or Fax: Run OCR (existing flow)
                try:
                    # Use a fresh session for OCR processing
                    with get_db_session() as db:
                        # Reload packet_document (use packet_document_id from resume_state or from Transaction A)
                        packet_document_id = packet_document.packet_document_id if packet_document else None
                        if not packet_document_id and resume_state:
                            packet_document_id = resume_state.packet_document.packet_document_id
                        if not packet_document_id:
                            raise DocumentProcessorError("Cannot process OCR: packet_document_id not found")
                        
                        packet_document_db = db.query(PacketDocumentDB).filter(
                            PacketDocumentDB.packet_document_id == packet_document_id
                        ).first()
                        if not packet_document_db:
                            raise DocumentProcessorError("Cannot process OCR: packet_document not found")
                        
                        # Process OCR
                        self._process_ocr(
                            db=db,
                            packet_document=packet_document_db,
                            split_result=split_result,
                            temp_files_to_cleanup=temp_files_to_cleanup
                        )
                        
                        # Transaction D: OCR results are already committed in _process_ocr
                        logger.info(f"✓ Transaction D committed: ocr_status=DONE")
                except Exception as ocr_error:
                    logger.error(f"OCR processing failed: {ocr_error}", exc_info=True)
                    # Update status to FAILED
                    packet_document_id = packet_document.packet_document_id if packet_document else None
                    if not packet_document_id and resume_state:
                        packet_document_id = resume_state.packet_document.packet_document_id
                    if packet_document_id:
                        with get_db_session() as db:
                            packet_document_db = db.query(PacketDocumentDB).filter(
                                PacketDocumentDB.packet_document_id == packet_document_id
                            ).first()
                            if packet_document_db:
                                packet_document_db.ocr_status = 'FAILED'
                                db.commit()
                    raise DocumentProcessorError(f"OCR processing failed: {ocr_error}") from ocr_error
            elif not self.channel_strategy.should_run_ocr():
                # Portal: Extract from payload (NEW)
                try:
                    # Use a fresh session for Portal processing
                    with get_db_session() as db:
                        # Reload packet_document
                        packet_document_id = packet_document.packet_document_id if packet_document else None
                        if not packet_document_id and resume_state:
                            packet_document_id = resume_state.packet_document.packet_document_id
                        if not packet_document_id:
                            raise DocumentProcessorError("Cannot process Portal fields: packet_document_id not found")
                        
                        packet_document_db = db.query(PacketDocumentDB).filter(
                            PacketDocumentDB.packet_document_id == packet_document_id
                        ).first()
                        if not packet_document_db:
                            raise DocumentProcessorError("Cannot process Portal fields: packet_document not found")
                        
                        # Process Portal fields from payload
                        self._process_portal_fields_from_payload(
                            db=db,
                            packet_document=packet_document_db,
                            split_result=split_result,
                            payload=message.payload
                        )
                        
                        # Transaction D: Portal results are already committed in _process_portal_fields_from_payload
                        logger.info(f"✓ Transaction D committed: ocr_status=DONE (from payload)")
                except Exception as portal_error:
                    logger.error(f"Portal field extraction failed: {portal_error}", exc_info=True)
                    # Update status to FAILED
                    packet_document_id = packet_document.packet_document_id if packet_document else None
                    if not packet_document_id and resume_state:
                        packet_document_id = resume_state.packet_document.packet_document_id
                    if packet_document_id:
                        with get_db_session() as db:
                            packet_document_db = db.query(PacketDocumentDB).filter(
                                PacketDocumentDB.packet_document_id == packet_document_id
                            ).first()
                            if packet_document_db:
                                packet_document_db.ocr_status = 'FAILED'
                                db.commit()
                    raise DocumentProcessorError(f"Portal field extraction failed: {portal_error}") from portal_error
            elif not self.ocr_service:
                logger.warning("OCR service not configured, skipping OCR")
        elif start_from == 'ocr':
            logger.info("Skipping OCR/Portal extraction: already completed")
        
        # Clean up all temp files
        for temp_file in temp_files_to_cleanup:
            try:
                Path(temp_file).unlink(missing_ok=True)
                logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp file {temp_file}: {cleanup_error}")
        
        logger.info(
            f"Successfully processed message {message.message_id}: "
            f"merged {len(parsed.documents)} documents into 1 consolidated document"
        )
    
    def _extract_submission_date_from_payload(
        self,
        payload: Dict[str, Any],
        parsed: Any,
        channel_type_id: Optional[int]
    ) -> Optional[datetime]:
        """
        Extract submission date from payload based on channel type.
        Returns the ORIGINAL timestamp as-is (no normalization).
        
        Normalization should happen only when calculating SLA/due dates.
        
        Channel-specific extraction:
        - ESMD (3): payload.submission_metadata.creationTime
        - Portal (1): payload.ocr.fields["Submitted Date"].value
        - Fax (2): payload.extracted_fields.fields["Submitted Date"].value
        
        Args:
            payload: Raw payload dictionary from message
            parsed: ParsedPayloadModel instance
            channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD)
        
        Returns:
            datetime with original timestamp (converted to UTC), or None if not found
        """
        if not channel_type_id:
            return None
        
        submission_date_str = None
        
        try:
            # ESMD: Extract from submission_metadata.creationTime
            if channel_type_id == 3:  # ESMD
                submission_metadata = getattr(parsed, 'submission_metadata', None) if parsed else None
                if isinstance(submission_metadata, dict):
                    submission_date_str = submission_metadata.get('creationTime')
            
            # Portal: Extract from ocr.fields["Submitted Date"].value
            elif channel_type_id == 1:  # Portal
                if payload and isinstance(payload, dict):
                    ocr_data = payload.get('ocr', {})
                    if isinstance(ocr_data, dict):
                        fields = ocr_data.get('fields', {})
                        if isinstance(fields, dict):
                            submitted_date_field = fields.get('Submitted Date', {})
                            if isinstance(submitted_date_field, dict):
                                submission_date_str = submitted_date_field.get('value')
            
            # Fax: Extract from submission_metadata.creationTime from original payload only
            # (No OCR fallback - only use original payload data)
            elif channel_type_id == 2:  # Fax
                submission_metadata = getattr(parsed, 'submission_metadata', None) if parsed else None
                if isinstance(submission_metadata, dict):
                    submission_date_str = submission_metadata.get('creationTime')
            
            # Parse the date string if found (returns raw timestamp, no normalization)
            if submission_date_str:
                return self._parse_date(submission_date_str)
        
        except Exception as e:
            logger.warning(
                f"Failed to extract submission date for channel_type_id={channel_type_id}: {e}",
                exc_info=True
            )
        
        return None
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse ISO 8601 date string and return raw timestamp (no normalization).
        Preserves the original timestamp from the payload.
        
        Normalization should happen only when calculating SLA/due dates.
        
        Args:
            date_str: ISO 8601 date string (e.g., "2026-01-06T14:25:33.4392211-05:00")
        
        Returns:
            datetime with original timestamp (converted to UTC), or None if parsing fails
        """
        if not date_str or not isinstance(date_str, str):
            return None
        
        try:
            from dateutil import parser
            
            # Parse the date string
            parsed_date = parser.parse(date_str)
            
            # Ensure timezone-aware (convert to UTC if needed)
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            else:
                parsed_date = parsed_date.astimezone(timezone.utc)
            
            # Return raw timestamp (no normalization to midnight)
            return parsed_date
        
        except Exception as e:
            logger.warning(f"Failed to parse submission date '{date_str}': {e}")
            return None
    
    def _normalize_submission_type(self, submission_type: Optional[str]) -> Optional[str]:
        """
        Normalize submission type value to 'Expedited' or 'Standard'.
        
        Uses partial matching (starts with) to handle values like:
        - 'expedited-initial' -> 'Expedited'
        - 'standard-initial' -> 'Standard'
        - 'expedited-someother' -> 'Expedited'
        - 'standard-some other value' -> 'Standard'
        
        Args:
            submission_type: Raw submission type value from OCR/payload
            
        Returns:
            'Expedited', 'Standard', or None (if unrecognized)
        """
        if not submission_type:
            return None
        
        value_lower = submission_type.strip().lower()
        
        # Expedited keywords - check if value starts with any of these
        expedited_keywords = ['expedited', 'expedite', 'urgent', 'rush']
        for keyword in expedited_keywords:
            if value_lower.startswith(keyword):
                return 'Expedited'
        
        # Standard keywords - check if value starts with any of these
        standard_keywords = ['standard', 'normal', 'routine', 'regular']
        for keyword in standard_keywords:
            if value_lower.startswith(keyword):
                return 'Standard'
        
        # Unrecognized - return None for manual review
        return None
    
    def _calculate_due_date(self, received_date: datetime, submission_type: Optional[str] = None) -> datetime:
        """
        Calculate due date based on received_date and submission_type.
        Normalizes received_date to midnight for SLA calculation.
        
        SLA rules:
        - Expedited: 48 hours from received_date (normalized to midnight)
        - Standard: 72 hours from received_date (normalized to midnight, default)
        
        Args:
            received_date: When the packet was received (raw timestamp - will be normalized to midnight)
            submission_type: "Expedited" or "Standard" (defaults to "Standard")
        
        Returns:
            Due date timestamp (at midnight UTC)
        """
        # Ensure timezone-aware
        if received_date.tzinfo is None:
            received_date = received_date.replace(tzinfo=timezone.utc)
        
        # Normalize received_date to midnight for SLA calculation (extract date only)
        normalized_received_date = datetime(
            year=received_date.year,
            month=received_date.month,
            day=received_date.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=timezone.utc
        )
        
        # Determine SLA hours based on submission_type
        # Use helper function to normalize, but for due_date calculation we need a default
        normalized = self._normalize_submission_type(submission_type)
        if normalized == 'Expedited':
            sla_hours = 48  # Expedited: 48 hours
        else:
            sla_hours = 72  # Standard: 72 hours (default if None or Standard)
        
        # Calculate due date using normalized received_date
        due_date = normalized_received_date + timedelta(hours=sla_hours)
        
        # Normalize due date to midnight (SLA is based on date, not time)
        # Example: received_date = 2026-01-06 14:25:33, Standard (72h = 3 days)
        #          normalized_received_date = 2026-01-06 00:00:00
        #          due_date = 2026-01-09 00:00:00 (3 days later at midnight)
        normalized_due_date = datetime(
            year=due_date.year,
            month=due_date.month,
            day=due_date.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
            tzinfo=timezone.utc
        )
        
        return normalized_due_date
    
    def _get_or_create_packet(
        self,
        db: Session,
        decision_tracking_id: str,
        unique_id: str,
        esmd_transaction_id: str,
        received_date: Optional[datetime] = None,
        channel_type_id: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> PacketDB:
        """
        Get existing packet or create new one.
        
        Idempotency: Uses decision_tracking_id with concurrency-safe insert.
        Database UNIQUE constraint ensures exactly one packet per decision_tracking_id.
        
        Args:
            db: Database session
            decision_tracking_id: Decision tracking ID (UUID)
            unique_id: Unique identifier for the message
            esmd_transaction_id: eSMD transaction ID
            received_date: Optional timestamp for when the message was received (from message.created_at)
                           If not provided, uses current time
            channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD)
            payload: Optional payload dictionary (used to extract packet_id for Portal channel)
            
        Returns:
            PacketDB instance (existing or newly created)
            
        Note:
            - external_id: Generated by ServiceOps (SVC-YYYY-XXXXXX format) for UI display
            - case_id: Channel-specific identifier:
              * Portal: payload.packet_id (PKT-YYYY-XXXXXX format)
              * ESMD: esmdTransactionId from payload.submission_metadata
              * Fax: NULL (no channel-specific ID)
        """
        # First, try to find existing packet by decision_tracking_id
        existing_packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == decision_tracking_id
        ).first()
        
        if existing_packet:
            logger.info(
                f"REUSED existing packet: packet_id={existing_packet.packet_id}, "
                f"external_id={existing_packet.external_id}, "
                f"case_id={existing_packet.case_id}, "
                f"decision_tracking_id={decision_tracking_id}"
            )
            return existing_packet
        
        # Packet doesn't exist - create new one
        # Generate external_id: SVC-YYYY-XXXXXXX format (7 digits for better uniqueness)
        # Uses last 7 digits of timestamp + microseconds for better collision resistance
        now = datetime.now(timezone.utc)
        timestamp_int = int(now.timestamp())
        microseconds = now.microsecond
        
        # Use last 7 digits of timestamp + last digit of microseconds for better uniqueness
        # This gives us 10 million combinations per year instead of 1 million
        timestamp_suffix = str(timestamp_int)[-7:]  # Last 7 digits of timestamp
        microsecond_digit = str(microseconds)[-1]  # Last digit of microseconds
        suffix = f"{timestamp_suffix}{microsecond_digit}"[:7]  # Ensure 7 digits total
        external_id = f"SVC-{now.year}-{suffix}"
        
        # Ensure external_id uniqueness with progressive digit expansion
        # If collision occurs, expand to 8 digits, then 9, then 10, etc.
        max_retries = 100
        retry_count = 0
        digit_count = 7  # Start with 7 digits
        
        while db.query(PacketDB).filter(PacketDB.external_id == external_id).first():
            retry_count += 1
            if retry_count >= max_retries:
                raise Exception(
                    f"Failed to generate unique external_id after {max_retries} attempts "
                    f"for decision_tracking_id={decision_tracking_id}. "
                    f"This indicates extremely high packet creation rate."
                )
            
            # Get fresh timestamp
            now = datetime.now(timezone.utc)
            timestamp_int = int(now.timestamp())
            microseconds = now.microsecond
            
            # Progressive expansion: 7 -> 8 -> 9 -> 10 digits
            # This ensures we can handle high-volume scenarios
            if retry_count <= 10:
                digit_count = 7
            elif retry_count <= 30:
                digit_count = 8
            elif retry_count <= 60:
                digit_count = 9
            else:
                digit_count = 10
            
            # Generate suffix with progressive digit count
            # Start with 7 digits (timestamp + microseconds), expand as needed
            if digit_count == 7:
                # 7 digits: last 7 of timestamp + last digit of microseconds
                timestamp_suffix = str(timestamp_int)[-7:]
                microsecond_digit = str(microseconds)[-1]
                suffix = f"{timestamp_suffix}{microsecond_digit}"[:7]
            elif digit_count == 8:
                # 8 digits: last 7 of timestamp + last 2 digits of microseconds
                timestamp_suffix = str(timestamp_int)[-7:]
                microsecond_digits = str(microseconds).zfill(6)[-2:]
                suffix = f"{timestamp_suffix}{microsecond_digits}"[:8]
            elif digit_count == 9:
                # 9 digits: last 7 of timestamp + last 3 digits of microseconds
                timestamp_suffix = str(timestamp_int)[-7:]
                microsecond_digits = str(microseconds).zfill(6)[-3:]
                suffix = f"{timestamp_suffix}{microsecond_digits}"[:9]
            else:  # digit_count == 10
                # 10 digits: last 7 of timestamp + last 4 digits of microseconds
                timestamp_suffix = str(timestamp_int)[-7:]
                microsecond_digits = str(microseconds).zfill(6)[-4:]
                suffix = f"{timestamp_suffix}{microsecond_digits}"[:10]
            
            external_id = f"SVC-{now.year}-{suffix}"
        
        # Use provided received_date (from message.created_at) or current time
        packet_received_date = received_date if received_date else now
        
        # Calculate initial due_date (default to Standard 72 hours, will be updated when submission_type is extracted)
        initial_due_date = self._calculate_due_date(packet_received_date, submission_type="Standard")
        
        # Extract channel-specific identifier for case_id:
        # - Portal (channel_type_id=1): payload.packet_id (PKT-YYYY-XXXXXX format)
        # - ESMD (channel_type_id=3): esmdTransactionId from payload.submission_metadata
        # - Fax (channel_type_id=2): NULL (no channel-specific ID)
        case_id_value = None
        if channel_type_id == 1 and payload and isinstance(payload, dict):  # Portal channel
            case_id_value = payload.get('packet_id')  # e.g., "PKT-2026-000074"
            if case_id_value:
                logger.info(
                    f"Extracted packet_id from Portal payload for case_id: {case_id_value} "
                    f"(external_id will be {external_id})"
                )
            else:
                logger.debug(
                    f"Portal channel but no packet_id in payload, case_id will be NULL"
                )
        elif channel_type_id == 3 and esmd_transaction_id:  # ESMD channel
            # Store esmdTransactionId in case_id for ESMD cases
            # This provides a channel-specific identifier (like Portal's packet_id)
            case_id_value = esmd_transaction_id
            logger.info(
                f"Storing esmdTransactionId in case_id for ESMD channel: {case_id_value} "
                f"(external_id will be {external_id})"
            )
        # For Fax (channel_type_id=2), case_id remains NULL
        
        # Create minimal packet (required fields only)
        # Note: Many fields are required but we don't have data from payload yet
        # We'll use placeholder values that can be updated later via OCR
        packet = PacketDB(
            external_id=external_id,
            decision_tracking_id=decision_tracking_id,  # Use dedicated column for idempotency
            case_id=case_id_value,  # Portal's packet_id (PKT- format) or NULL for ESMD/Fax
            beneficiary_name="TBD",  # Will be updated from OCR
            beneficiary_mbi="TBD",  # Will be updated from OCR
            provider_name="TBD",  # Will be updated from OCR
            provider_npi="TBD",  # Will be updated from OCR
            service_type="Prior Authorization",  # Default
            received_date=packet_received_date,  # Use message.created_at timestamp
            due_date=initial_due_date,  # Initial due_date (Standard 72h), will be updated when submission_type is extracted
            channel_type_id=channel_type_id,  # Store channel type ID
            detailed_status='Pending - New'  # Required NOT NULL field - explicit default for new packets
        )
        
        try:
            db.add(packet)
            db.flush()  # Flush to get packet_id and trigger constraint check
            
            logger.info(
                f"CREATED new packet: packet_id={packet.packet_id}, "
                f"external_id={packet.external_id}, "
                f"case_id={packet.case_id}, "
                f"decision_tracking_id={decision_tracking_id}"
            )
            return packet
            
        except IntegrityError as e:
            # Handle unique constraint violation (concurrency case)
            # Another worker may have created the packet between our check and insert
            db.rollback()
            
            # Check if it's a unique constraint violation on decision_tracking_id
            error_str = str(e.orig) if hasattr(e, 'orig') else str(e)
            if 'uq_packet_decision_tracking_id' in error_str or 'unique constraint' in error_str.lower():
                # Re-fetch the packet that was created by the other worker
                existing_packet = db.query(PacketDB).filter(
                    PacketDB.decision_tracking_id == decision_tracking_id
                ).first()
                
                if existing_packet:
                    logger.info(
                        f"REUSED packet after conflict: packet_id={existing_packet.packet_id}, "
                        f"external_id={existing_packet.external_id}, "
                        f"decision_tracking_id={decision_tracking_id} "
                        f"(another worker created it concurrently)"
                    )
                    return existing_packet
            
            # Re-raise if it's not a unique constraint violation we can handle
            logger.error(
                f"Failed to create packet for decision_tracking_id={decision_tracking_id}: {e}",
                exc_info=True
            )
            raise
    
    def _get_or_create_consolidated_document(
        self,
        db: Session,
        packet_id: int
    ) -> PacketDocumentDB:
        """
        Get or create the single consolidated packet_document for a packet.
        
        Enforces: EXACTLY ONE packet_document per packet_id (consolidated workflow).
        Uses REPLACE policy: if document exists, it will be reused and updated.
        
        Args:
            db: Database session
            packet_id: Packet ID (bigint)
            
        Returns:
            PacketDocumentDB instance (existing or newly created, not yet committed)
        """
        # Check if consolidated document already exists for this packet
        existing_doc = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet_id
        ).first()
        
        if existing_doc:
            logger.info(
                f"Found existing consolidated document for packet_id={packet_id}: "
                f"packet_document_id={existing_doc.packet_document_id}, "
                f"external_id={existing_doc.external_id}"
            )
            return existing_doc
        
        # Create new consolidated document
        # external_id is deterministic: DOC-{packet_id}
        external_id = f"DOC-{packet_id}"
        
        # Ensure external_id uniqueness (in case of collision with old data)
        counter = 1
        base_external_id = external_id
        while db.query(PacketDocumentDB).filter(PacketDocumentDB.external_id == external_id).first():
            external_id = f"{base_external_id}-{counter}"
            counter += 1
            logger.warning(
                f"external_id collision for DOC-{packet_id}, using {external_id} instead"
            )
        
        # Get default document_type_id
        document_type_id = 1  # Default to first document type
        
        # Create consolidated packet_document
        packet_document = PacketDocumentDB(
            external_id=external_id,
            packet_id=packet_id,
            file_name=f"packet_{packet_id}.pdf",  # Will be updated with actual consolidated file name after upload
            document_unique_identifier="CONSOLIDATED",  # Constant identifier for consolidated docs
            page_count=0,  # Will be updated after splitting
            file_size="0 B",  # Will be updated after merging
            uploaded_at=datetime.now(timezone.utc),
            document_type_id=document_type_id,
            split_status='NOT_STARTED',
            ocr_status='NOT_STARTED',
        )
        
        logger.info(
            f"Created new consolidated document for packet_id={packet_id}: "
            f"external_id={external_id}"
        )
        
        return packet_document
    
    def _get_or_create_empty_document(
        self,
        db: Session,
        packet: PacketDB,
        message: SendServiceOpsDB
    ) -> PacketDocumentDB:
        """
        Create packet_document with empty state when documents are missing.
        
        This ensures 100% reliability - all messages with decision_tracking_id
        will have a packet and packet_document record, even if documents are missing.
        
        Args:
            db: Database session
            packet: PacketDB instance
            message: SendServiceOpsDB message (for context)
            
        Returns:
            PacketDocumentDB instance with empty document state
        """
        # Check if document already exists
        existing = db.query(PacketDocumentDB).filter(
            PacketDocumentDB.packet_id == packet.packet_id
        ).first()
        
        if existing:
            logger.info(
                f"Found existing document for packet_id={packet.packet_id}: "
                f"packet_document_id={existing.packet_document_id}"
            )
            return existing
        
        # Create external_id
        external_id = f"DOC-{packet.packet_id}"
        counter = 1
        base_external_id = external_id
        while db.query(PacketDocumentDB).filter(PacketDocumentDB.external_id == external_id).first():
            external_id = f"{base_external_id}-{counter}"
            counter += 1
        
        # Create empty document state
        document = PacketDocumentDB(
            external_id=external_id,
            packet_id=packet.packet_id,
            file_name="no_documents.pdf",  # Placeholder name
            document_unique_identifier="NO_DOCUMENTS",  # Constant identifier
            page_count=0,
            file_size="0 B",
            uploaded_at=datetime.now(timezone.utc),
            document_type_id=1,  # Default document type
            split_status='SKIPPED',  # No documents to split
            ocr_status='SKIPPED',  # No documents to OCR
            extracted_fields={
                "fields": {},
                "source": "MISSING_DOCUMENTS",
                "error": "No documents found in payload",
                "message_id": message.message_id,
                "decision_tracking_id": packet.decision_tracking_id
            },
            pages_metadata=[],
            ocr_metadata=None
        )
        
        db.add(document)
        logger.info(
            f"Created empty document state for packet_id={packet.packet_id}: "
            f"external_id={external_id}, decision_tracking_id={packet.decision_tracking_id}"
        )
        
        return document
    
    def _create_packet_document(
        self,
        db: Session,
        packet_id: int,
        document,
        split_result
    ) -> PacketDocumentDB:
        """
        DEPRECATED: Use _get_or_create_consolidated_document() instead.
        
        This method is kept for backward compatibility but should not be used
        in the consolidated workflow.
        """
        # Generate external_id: DOC-XXXX format
        # Use last 4 chars of document_unique_identifier or generate unique
        if len(document.document_unique_identifier) >= 4:
            doc_id_suffix = document.document_unique_identifier[-4:].upper()
        else:
            # Generate unique suffix from UUID
            doc_id_suffix = str(uuid.uuid4())[:4].upper().replace('-', '')
        external_id = f"DOC-{doc_id_suffix}"
        
        # Ensure uniqueness
        counter = 1
        base_external_id = external_id
        while db.query(PacketDocumentDB).filter(PacketDocumentDB.external_id == external_id).first():
            external_id = f"{base_external_id}-{counter}"
            counter += 1
        
        # Get default document_type_id (use 1 as default, or lookup from table)
        # TODO: Lookup from service_ops.document_type table for proper type
        document_type_id = 1  # Default to first document type (typically "OTHER" or "COVER_LETTER")
        
        # Format file size as string (e.g., "245 KB")
        file_size_str = self._format_file_size(document.file_size)
        
        # Create packet_document
        packet_document = PacketDocumentDB(
            external_id=external_id,
            packet_id=packet_id,
            file_name=document.file_name,
            document_unique_identifier=document.document_unique_identifier,  # Store for idempotency
            page_count=split_result.page_count,
            file_size=file_size_str,
            uploaded_at=datetime.now(timezone.utc),
            document_type_id=document_type_id,
            # Page tracking and OCR metadata
            processing_path=split_result.processing_path,
            pages_metadata=split_result.pages_metadata,
            split_status='DONE',
            ocr_status='NOT_STARTED',
            # Note: checksum not stored in packet_document table
        )
        
        return packet_document
    
    def _process_ocr(
        self,
        db: Session,
        packet_document: PacketDocumentDB,
        split_result: SplitResult,
        temp_files_to_cleanup: list
    ) -> None:
        """
        Process OCR on all split pages
        
        Args:
            db: Database session
            packet_document: PacketDocumentDB instance to update
            split_result: SplitResult with pages and local paths
            temp_files_to_cleanup: List of temp file paths (for cleanup tracking)
        """
        # Check if OCR already completed (idempotency)
        # NOTE: For consolidated workflow with REPLACE policy, OCR status is reset before calling this,
        # so this check is mainly for safety/concurrency
        if packet_document.ocr_status == 'DONE':
            logger.info(
                f"OCR already completed for document {packet_document.document_unique_identifier}, "
                f"skipping OCR processing (likely concurrent processing)"
            )
            return
        
        logger.info(
            f"Starting OCR processing for document {packet_document.document_unique_identifier}, "
            f"{split_result.page_count} pages"
        )
        
        # Set OCR status to IN_PROGRESS
        packet_document.ocr_status = 'IN_PROGRESS'
        db.flush()
        
        # Run OCR on each split page SEQUENTIALLY (one at a time) to reduce load on OCR service
        # This prevents overwhelming the service with parallel requests
        page_ocr_results = []
        ocr_errors = []
        failed_pages = []  # Store failed pages for retry at end
        
        delay_between_requests = settings.ocr_delay_between_requests
        
        # Handle resume case: if pages list is empty but page_count > 0, use pages_metadata
        pages_to_process = split_result.pages if split_result.pages else []
        if not pages_to_process and split_result.page_count > 0:
            # Resume case: pages were already uploaded, get paths from metadata
            page_blob_paths = get_page_blob_paths_from_metadata(packet_document)
            if page_blob_paths:
                # Download pages as needed (this should have been done before calling _process_ocr)
                logger.warning("split_result.pages is empty but page_count > 0 - this should not happen in resume flow")
        
        # Limit to first 10 pages only (fail fast to manual review if needed)
        max_pages_to_process = 10
        pages_to_process_limited = pages_to_process[:max_pages_to_process]
        
        if len(pages_to_process) > max_pages_to_process:
            logger.info(
                f"Limiting OCR to first {max_pages_to_process} pages "
                f"(document has {len(pages_to_process)} total pages). "
                f"If OCR fails, remaining pages will be available for manual review."
            )
        
        logger.info(
            f"Processing {len(pages_to_process_limited)} pages sequentially "
            f"with {delay_between_requests}s delay between requests"
        )
        
        coversheet_found = False
        coversheet_page_number = None
        
        # Track total OCR attempts across all pages (max 3 total)
        total_ocr_attempts = 0
        max_total_attempts = 3
        
        for page_idx, page in enumerate(pages_to_process_limited):
            # Check if we've exceeded max total attempts
            if total_ocr_attempts >= max_total_attempts:
                remaining_count = len(pages_to_process_limited) - page_idx
                logger.warning(
                    f"Max total OCR attempts ({max_total_attempts}) reached. "
                    f"Stopping OCR processing. {remaining_count} pages remaining. "
                    f"Will proceed to graceful failure handler."
                )
                # Mark remaining pages as skipped
                for remaining_page in pages_to_process_limited[page_idx:]:
                    page_ocr_results.append({
                        'page_number': remaining_page.page_number,
                        'fields': {},
                        'overall_document_confidence': 0.0,
                        'duration_ms': 0,
                        'coversheet_type': '',
                        'doc_type': '',
                        'error': f'Skipped: max total attempts ({max_total_attempts}) reached',
                        'raw': {}
                    })
                break  # Exit loop, proceed to graceful failure
            
            try:
                total_ocr_attempts += 1
                logger.info(
                    f"Running OCR on page {page.page_number}: {page.local_path} "
                    f"(attempt {total_ocr_attempts}/{max_total_attempts} total)"
                )
                
                # Run OCR on the local PDF file (OCR service has its own retries, but we track total attempts)
                ocr_result = self.ocr_service.run_ocr_on_pdf(page.local_path)
                
                fields = ocr_result.get('fields', {})
                field_count = len(fields)
                confidence = ocr_result.get('overall_document_confidence', 0.0)
                
                # Store per-page result
                page_ocr_results.append({
                    'page_number': page.page_number,
                    'fields': fields,
                    'overall_document_confidence': confidence,
                    'duration_ms': ocr_result.get('duration_ms', 0),
                    'coversheet_type': ocr_result.get('coversheet_type', ''),
                    'doc_type': ocr_result.get('doc_type', ''),
                    'raw': ocr_result.get('raw', {})
                })
                
                logger.info(
                    f"OCR completed for page {page.page_number}: "
                    f"{field_count} fields, "
                    f"confidence={confidence:.3f}, "
                    f"duration={ocr_result.get('duration_ms', 0)}ms"
                )
                
                # Check if this page is a strong coversheet candidate
                # Stop processing if we find a strong candidate early
                if settings.ocr_stop_after_coversheet and not coversheet_found:
                    if (confidence >= settings.ocr_coversheet_confidence_threshold and 
                        field_count >= settings.ocr_min_coversheet_fields):
                        coversheet_found = True
                        coversheet_page_number = page.page_number
                        logger.info(
                            f"✓ Strong coversheet candidate found at page {page.page_number} "
                            f"(confidence={confidence:.3f}, fields={field_count}). "
                            f"Stopping OCR processing for remaining pages."
                        )
                        break  # Stop processing remaining pages
                    # Note: If no page meets threshold, we'll process all pages
                    # and use coversheet detector to find best page
            
            except OCRServiceError as e:
                logger.error(
                    f"OCR failed for page {page.page_number} (attempt {total_ocr_attempts}/{max_total_attempts}): {e}",
                    exc_info=True
                )
                ocr_errors.append(f"Page {page.page_number}: {e}")
                # Mark this page as failed in results
                page_ocr_results.append({
                    'page_number': page.page_number,
                    'fields': {},
                    'overall_document_confidence': 0.0,
                    'duration_ms': 0,
                    'coversheet_type': '',
                    'doc_type': '',
                    'error': str(e),
                    'raw': {}
                })
                # Don't retry failed pages at end - we have max 3 total attempts
                # If we've hit the limit, we'll proceed to graceful failure
            
            # Add delay between requests to reduce load on OCR service
            if delay_between_requests > 0 and page != pages_to_process[-1]:  # Don't delay after last page
                time.sleep(delay_between_requests)
        
        # If we stopped early due to finding coversheet, log remaining pages
        if coversheet_found:
            remaining_pages = len(pages_to_process) - len(page_ocr_results)
            if remaining_pages > 0:
                logger.info(
                    f"Skipped OCR processing for {remaining_pages} remaining pages "
                    f"(strong coversheet candidate found at page {coversheet_page_number})"
                )
        elif settings.ocr_stop_after_coversheet:
            # No page met the threshold - we processed all pages
            # coversheet_page_number will be set by coversheet detector below
            logger.info(
                f"No page met the strong coversheet threshold "
                f"(confidence >= {settings.ocr_coversheet_confidence_threshold}, "
                f"fields >= {settings.ocr_min_coversheet_fields}). "
                f"Processed all {len(page_ocr_results)} pages. "
                f"Will use coversheet detector to find best page from all processed pages."
            )
        
        # Log summary
        successful_pages = len([r for r in page_ocr_results if r.get('error') is None])
        failed_pages_count = len([r for r in page_ocr_results if r.get('error') is not None])
        logger.info(
            f"OCR processing complete: {successful_pages} succeeded, {failed_pages_count} failed "
            f"(out of {len(page_ocr_results)} processed pages, {len(pages_to_process_limited)} total pages processed)"
        )
        
        # Check if we should proceed to graceful failure
        # Condition: All pages failed OR max total attempts reached AND no successful pages
        all_pages_failed = len(ocr_errors) > 0 and len(ocr_errors) == len(page_ocr_results)
        max_attempts_reached = total_ocr_attempts >= max_total_attempts
        should_graceful_fail = (all_pages_failed or max_attempts_reached) and successful_pages == 0
        
        if should_graceful_fail:
            if all_pages_failed:
                logger.warning(
                    f"All {len(page_ocr_results)} pages failed OCR after {total_ocr_attempts} total attempts. "
                    f"Proceeding to graceful failure handler."
                )
            elif max_attempts_reached:
                logger.warning(
                    f"Max total OCR attempts ({max_total_attempts}) reached after {total_ocr_attempts} attempts. "
                    f"No successful pages. Proceeding to graceful failure handler."
                )
            # Call graceful failure handler
            self._handle_ocr_failure_gracefully(
                db=db,
                packet_document=packet_document,
                split_result=split_result,
                page_ocr_results=page_ocr_results,
                total_attempts=total_ocr_attempts
            )
            return  # Exit early - graceful failure handler has set everything up
        
        # Normal flow: We have at least one successful page
        # Detect coversheet page
        # If we stopped early due to finding a strong candidate, use that page
        if coversheet_found and coversheet_page_number:
            logger.info(f"Using early-detected coversheet: page {coversheet_page_number}")
        else:
            # Otherwise, use coversheet detector to find best page from processed pages
            try:
                # Only use successful pages for coversheet detection
                successful_page_results = [r for r in page_ocr_results if r.get('error') is None]
                if successful_page_results:
                    coversheet_page_number = self.coversheet_detector.detect_coversheet_page(successful_page_results)
                    logger.info(f"Detected coversheet via detector: page {coversheet_page_number}")
                else:
                    # No successful pages but we didn't graceful fail (shouldn't happen, but safety)
                    logger.warning("No successful pages for coversheet detection, setting to NULL")
                    coversheet_page_number = None
            except Exception as e:
                logger.warning(f"Coversheet detection failed: {e}, setting to NULL")
                coversheet_page_number = None
        
        # Get coversheet OCR result for Part classification
        coversheet_ocr = None
        if coversheet_page_number:
            for page_result in page_ocr_results:
                if page_result.get('page_number') == coversheet_page_number and page_result.get('error') is None:
                    coversheet_ocr = page_result
                    break
        
        # Classify Part A/B
        if coversheet_ocr:
            part_type = self.part_classifier.classify_part_type(coversheet_ocr)
            logger.info(f"Classified as: {part_type}")
        else:
            logger.warning("Coversheet OCR result not found, defaulting to UNKNOWN")
            part_type = "UNKNOWN"
        
        # Build ocr_metadata
        # Include all pages: processed pages + skipped pages (if early stopping occurred)
        ocr_metadata_pages = []
        processed_page_numbers = {r.get('page_number') for r in page_ocr_results}
        
        # Use pages_to_process if available, otherwise use pages_metadata
        if not pages_to_process and packet_document.pages_metadata:
            # Resume case: build from pages_metadata
            pages_meta = packet_document.pages_metadata.get('pages', [])
            for page_meta in pages_meta:
                page_num = page_meta.get('page_number')
                if page_num in processed_page_numbers:
                    # Page was processed - use OCR result
                    result = next(r for r in page_ocr_results if r.get('page_number') == page_num)
                    ocr_metadata_pages.append({
                        'page_number': page_num,
                        'fields': result.get('fields', {}),
                        'duration_ms': result.get('duration_ms', 0),
                        'overall_document_confidence': result.get('overall_document_confidence', 0.0),
                        'error': result.get('error'),
                        'status': 'processed'
                    })
                else:
                    # Page was skipped
                    ocr_metadata_pages.append({
                        'page_number': page_num,
                        'fields': {},
                        'duration_ms': 0,
                        'overall_document_confidence': 0.0,
                        'error': None,
                        'status': 'skipped',
                        'skip_reason': f'Early stopping: coversheet found at page {coversheet_page_number}' if coversheet_found else 'Not processed'
                    })
        else:
            # Normal flow: use pages_to_process_limited
            for page in pages_to_process_limited:
                page_num = page.page_number
                if page_num in processed_page_numbers:
                    # Page was processed - use OCR result
                    result = next(r for r in page_ocr_results if r.get('page_number') == page_num)
                    ocr_metadata_pages.append({
                        'page_number': page_num,
                        'fields': result.get('fields', {}),
                        'duration_ms': result.get('duration_ms', 0),
                        'overall_document_confidence': result.get('overall_document_confidence', 0.0),
                        'error': result.get('error'),
                        'status': 'processed'
                    })
                else:
                    # Page was skipped due to early stopping
                    ocr_metadata_pages.append({
                        'page_number': page_num,
                        'fields': {},
                        'duration_ms': 0,
                        'overall_document_confidence': 0.0,
                        'error': None,
                        'status': 'skipped',
                        'skip_reason': f'Early stopping: coversheet found at page {coversheet_page_number}'
                    })
        
        ocr_metadata = {
            'version': 'v1',
            'pages': ocr_metadata_pages,
            'coversheet_page_number': coversheet_page_number,
            'part_type': part_type
        }
        
        # Also update pages_metadata to include OCR confidence for each page
        if packet_document.pages_metadata:
            pages = packet_document.pages_metadata.get('pages', [])
            processed_page_numbers = {r.get('page_number') for r in page_ocr_results}
            for page_meta in pages:
                page_num = page_meta.get('page_number')
                if page_num in processed_page_numbers:
                    # Find matching OCR result
                    for ocr_result in page_ocr_results:
                        if ocr_result.get('page_number') == page_num:
                            page_meta['ocr_confidence'] = ocr_result.get('overall_document_confidence', 0.0)
                            page_meta['ocr_status'] = 'processed'
                            break
                else:
                    # Page was skipped due to early stopping
                    page_meta['ocr_confidence'] = 0.0
                    page_meta['ocr_status'] = 'skipped'
                    page_meta['skip_reason'] = f'Early stopping: coversheet found at page {coversheet_page_number}'
        
        # Update packet_document
        packet_document.ocr_metadata = ocr_metadata
        flag_modified(packet_document, 'ocr_metadata')  # CRITICAL: Flag JSONB column as modified
        packet_document.coversheet_page_number = coversheet_page_number
        packet_document.part_type = part_type
        packet_document.ocr_status = 'DONE'
        
        # Populate extracted_fields with coversheet page's full OCR result (IMMUTABLE BASELINE)
        # This includes all fields with their values and confidence scores
        # ALSO set updated_extracted_fields to same value (working copy starts from baseline)
        if coversheet_ocr:
            baseline_payload = {
                'fields': coversheet_ocr.get('fields', {}),  # All fields with values and confidence
                'coversheet_type': coversheet_ocr.get('coversheet_type', ''),
                'doc_type': coversheet_ocr.get('doc_type', ''),
                'overall_document_confidence': coversheet_ocr.get('overall_document_confidence', 0.0),
                'duration_ms': coversheet_ocr.get('duration_ms', 0),
                'page_number': coversheet_page_number,
                'raw': coversheet_ocr.get('raw', {}),  # Store raw OCR response for debugging
                'source': 'OCR_INITIAL'  # Mark as initial OCR baseline
            }
            # Set extracted_fields as IMMUTABLE BASELINE (never modified after this)
            packet_document.extracted_fields = baseline_payload
            flag_modified(packet_document, 'extracted_fields')  # CRITICAL: Flag JSONB column as modified
            
            # Set updated_extracted_fields to same value (working copy starts from baseline)
            # Use deepcopy to avoid shared references
            import copy
            packet_document.updated_extracted_fields = copy.deepcopy(baseline_payload)
            flag_modified(packet_document, 'updated_extracted_fields')  # CRITICAL: Flag JSONB column as modified
            
            # Apply auto-fix to updated_extracted_fields (silent formatting fixes)
            try:
                from app.services.field_auto_fix import apply_auto_fix_to_fields
                fixed_fields, auto_fix_results = apply_auto_fix_to_fields(packet_document.updated_extracted_fields)
                packet_document.updated_extracted_fields = fixed_fields
                flag_modified(packet_document, 'updated_extracted_fields')
                
                if auto_fix_results:
                    logger.info(
                        f"Applied auto-fix to {len(auto_fix_results)} field(s): {list(auto_fix_results.keys())}"
                    )
            except Exception as e:
                logger.warning(
                    f"Error applying auto-fix to extracted fields: {str(e)}. "
                    f"Continuing without auto-fix."
                )
            
            logger.info(
                f"Populated extracted_fields (baseline) and updated_extracted_fields (working) with coversheet page {coversheet_page_number} OCR result "
                f"({len(coversheet_ocr.get('fields', {}))} fields)"
            )
        else:
            # No coversheet OCR result - this shouldn't happen in normal flow
            # (graceful failure would have been called earlier), but handle it
            logger.warning(
                f"No coversheet OCR result found to populate extracted_fields "
                f"(coversheet_page_number={coversheet_page_number}). "
                f"Setting empty structure."
            )
            # Set empty structure
            empty_payload = {
                'fields': {},
                'coversheet_type': '',
                'doc_type': '',
                'overall_document_confidence': 0.0,
                'duration_ms': 0,
                'page_number': coversheet_page_number,
                'raw': {},
                'source': 'OCR_INITIAL'
            }
            packet_document.extracted_fields = empty_payload
            flag_modified(packet_document, 'extracted_fields')
            # Use deepcopy to avoid shared references
            import copy
            packet_document.updated_extracted_fields = copy.deepcopy(empty_payload)
            flag_modified(packet_document, 'updated_extracted_fields')
            
            # Apply auto-fix (even for empty payload, in case fields are added later)
            try:
                from app.services.field_auto_fix import apply_auto_fix_to_fields
                fixed_fields, auto_fix_results = apply_auto_fix_to_fields(packet_document.updated_extracted_fields)
                packet_document.updated_extracted_fields = fixed_fields
                flag_modified(packet_document, 'updated_extracted_fields')
            except Exception as e:
                logger.warning(f"Error applying auto-fix to empty extracted fields: {str(e)}")
        
        # Update pages_metadata to mark coversheet
        if packet_document.pages_metadata:
            pages = packet_document.pages_metadata.get('pages', [])
            for page_meta in pages:
                if page_meta.get('page_number') == coversheet_page_number:
                    page_meta['is_coversheet'] = True
                    break
            # CRITICAL: Flag JSONB column as modified after nested dict update
            flag_modified(packet_document, 'pages_metadata')
        
        # PHASE 1 FIX: Persist OCR-extracted beneficiary/provider values to packet table
        # ROOT CAUSE: Previously, OCR values were only stored in packet_document.extracted_fields,
        # but packet table had TBD placeholders. The dashboard queries /api/packets which uses
        # packet_to_dto() with query-time OCR extraction, but this was unreliable.
        # SOLUTION: Persist OCR values to packet table after OCR completes, so dashboard
        # always shows correct values without needing query-time enrichment.
        # This ensures dashboard shows correct values without query-time enrichment
        if coversheet_ocr and coversheet_ocr.get('fields'):
            try:
                from app.models.packet_db import PacketDB
                from app.utils.packet_sync import sync_packet_from_extracted_fields
                from datetime import datetime, timezone
                
                # Get the packet to update
                packet = db.query(PacketDB).filter(
                    PacketDB.packet_id == packet_document.packet_id
                ).first()
                
                if packet:
                    # Use updated_extracted_fields to sync packet table
                    # This will update beneficiary, provider, HCPCS, procedure codes, submission_type
                    # Use updated_extracted_fields which contains the OCR baseline data (with auto-fix applied)
                    extracted_fields_data = packet_document.updated_extracted_fields or packet_document.extracted_fields
                    if extracted_fields_data:
                        sync_packet_from_extracted_fields(
                            packet=packet,
                            extracted_fields_dict=extracted_fields_data,
                            now=datetime.now(timezone.utc),
                            db=db
                        )
                        
                        # Run field validation after OCR ingestion
                        try:
                            from app.services.field_validation_service import validate_all_fields
                            from app.services.validation_persistence import save_field_validation_errors, update_packet_validation_flag
                            
                            validation_result = validate_all_fields(
                                extracted_fields=extracted_fields_data,
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
                                f"[_process_ocr] Field validation complete for packet {packet.external_id}. "
                                f"has_errors={validation_result['has_errors']}, "
                                f"error_count={len(validation_result.get('field_errors', {}))}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"[_process_ocr] Error running field validation for packet {packet.external_id}: {str(e)}. "
                                f"Continuing without validation."
                            )
                    
                    # Legacy extraction code (keeping for backward compatibility if needed)
                    # The sync_packet_from_extracted_fields function handles all field mapping
                    from app.utils.packet_converter import extract_from_ocr_fields
                    
                    beneficiary_last_name = extract_from_ocr_fields(
                        [packet_document], 
                        [
                            'Beneficiary Last Name', 'beneficiaryLastName', 'beneficiary_last_name',
                            'Patient Last Name', 'patientLastName', 'patient_last_name',
                            'Member Last Name', 'memberLastName', 'member_last_name',
                            'Last Name', 'lastName', 'last_name', 'lname'
                        ]
                    )
                    beneficiary_first_name = extract_from_ocr_fields(
                        [packet_document],
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
                            [packet_document],
                            [
                                'Beneficiary Name', 'beneficiaryName', 'beneficiary_name',
                                'Patient Name', 'patientName', 'patient_name',
                                'Member Name', 'memberName', 'member_name',
                                'Full Name', 'fullName', 'full_name'
                            ]
                        )
                    
                    ocr_beneficiary_mbi = extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Beneficiary Medicare ID',  # Exact match from OCR output
                            'Medicare ID', 'medicareId', 'MBI', 'mbi', 'Beneficiary MBI', 'beneficiaryMbi',
                            'Medicare Beneficiary Identifier', 'Medicare Number', 'medicareNumber',
                            'HICN', 'hicn', 'Health Insurance Claim Number'
                        ]
                    )
                    
                    # Extract provider info from OCR
                    # Note: OCR uses "Facility Provider Name" and "Attending Physician Name"
                    facility_name = extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Facility Provider Name',  # Exact match from OCR output
                            'Facility Name', 'facilityName', 'facility_name',
                            'Organization Name', 'organizationName', 'organization_name',
                            'Practice Name', 'practiceName', 'practice_name'
                        ]
                    )
                    physician_name = extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Attending Physician Name',  # Exact match from OCR output
                            'Physician Name', 'physicianName', 'physician_name',
                            'Ordering/Referring Physician Name', 'Ordering Physician Name',
                            'Referring Physician Name', 'Doctor Name', 'doctorName',
                            'Attending Physician', 'attendingPhysician'
                        ]
                    )
                    ocr_provider_name = facility_name or physician_name or extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Provider Name', 'providerName', 'provider_name',
                            'Rendering Provider Name', 'renderingProviderName',
                            'Billing Provider Name', 'billingProviderName'
                        ]
                    )
                    
                    facility_npi = extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Facility Provider NPI',  # Exact match from OCR output
                            'Facility NPI', 'facilityNpi', 'facility_npi',
                            'Organization NPI', 'organizationNpi', 'organization_npi'
                        ]
                    )
                    physician_npi = extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Attending Physician NPI',  # Exact match from OCR output (10 digits)
                            'Physician NPI', 'physicianNpi', 'physician_npi',
                            'Ordering/Referring Physician NPI', 'Ordering Physician NPI',
                            'Referring Physician NPI', 'Doctor NPI', 'doctorNpi'
                        ]
                    )
                    # Prefer Attending Physician NPI (usually 10 digits) over Facility Provider NPI (may be 9 digits)
                    ocr_provider_npi = physician_npi or facility_npi or extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Provider NPI', 'providerNpi', 'provider_npi',
                            'Rendering Provider NPI', 'renderingProviderNpi',
                            'Billing Provider NPI', 'billingProviderNpi',
                            'NPI', 'npi'  # Last resort - generic NPI field
                        ]
                    )
                    
                    # Update packet table only if current values are TBD/placeholder
                    # This preserves manually set values while filling in OCR-extracted ones
                    updated = False
                    if ocr_beneficiary_name and (not packet.beneficiary_name or packet.beneficiary_name == "TBD"):
                        packet.beneficiary_name = ocr_beneficiary_name
                        updated = True
                    
                    if ocr_beneficiary_mbi and (not packet.beneficiary_mbi or packet.beneficiary_mbi == "TBD"):
                        packet.beneficiary_mbi = ocr_beneficiary_mbi
                        updated = True
                    
                    if ocr_provider_name and (not packet.provider_name or packet.provider_name == "TBD"):
                        packet.provider_name = ocr_provider_name
                        updated = True
                    
                    # Extract provider_npi: must be 10 digits, leave as "TBD" if invalid (for manual review)
                    if ocr_provider_npi:
                        # Clean NPI: remove non-digits
                        npi_clean = ''.join(c for c in str(ocr_provider_npi) if c.isdigit())
                        if len(npi_clean) == 10:
                            if not packet.provider_npi or packet.provider_npi == "TBD" or packet.provider_npi == "0000000000":
                                packet.provider_npi = npi_clean
                                updated = True
                        elif len(npi_clean) == 9:
                            # Pad 9-digit NPI with leading zero (common OCR error)
                            npi_clean = '0' + npi_clean
                            if not packet.provider_npi or packet.provider_npi == "TBD" or packet.provider_npi == "0000000000":
                                packet.provider_npi = npi_clean
                                updated = True
                            logger.info(
                                f"Padded 9-digit NPI with leading zero: {ocr_provider_npi} -> {npi_clean}"
                            )
                        else:
                            logger.warning(
                                f"Invalid NPI extracted from OCR: {ocr_provider_npi} "
                                f"(expected 10 digits, got {len(npi_clean)}). Leaving as TBD for manual review."
                            )
                    # If no OCR NPI found, leave as "TBD" for manual review (don't set to "0000000000")
                    
                    # Extract submission type from OCR
                    ocr_submission_type = extract_from_ocr_fields(
                        [packet_document],
                        [
                            'Submission Type', 'submissionType', 'submission_type',
                            'Priority', 'priority'  # Fallback to priority if submission type not found
                        ]
                    )
                    
                    # Normalize submission type: map to Expedited or Standard
                    # Uses partial matching (starts with) to handle values like 'expedited-initial', 'standard-initial'
                    if ocr_submission_type:
                        submission_type_normalized = self._normalize_submission_type(ocr_submission_type)
                        if not submission_type_normalized:
                            logger.warning(
                                f"Unrecognized submission type from OCR: {ocr_submission_type}, leaving as NULL for manual review"
                            )
                        
                        if submission_type_normalized:
                            # Only update if we have a valid submission type
                            if not packet.submission_type or packet.submission_type != submission_type_normalized:
                                packet.submission_type = submission_type_normalized
                                # Update due_date based on new submission_type
                                packet.due_date = self._calculate_due_date(
                                    packet.received_date,
                                    submission_type=submission_type_normalized
                                )
                                updated = True
                    # If no submission_type from OCR, leave as None for manual review
                    # Don't set default - let someone manually review and set it
                    
                    if updated:
                        packet.updated_at = datetime.now(timezone.utc)
                        db.flush()
                        logger.info(
                            f"Updated packet {packet.external_id} with OCR-extracted values: "
                            f"beneficiary_name={ocr_beneficiary_name or 'unchanged'}, "
                            f"provider_name={ocr_provider_name or 'unchanged'}, "
                            f"provider_npi={'updated' if ocr_provider_npi else 'defaulted'}, "
                            f"submission_type={packet.submission_type or 'unchanged'}"
                        )
                    else:
                        logger.debug(
                            f"Packet {packet.external_id} already has non-TBD values, skipping OCR update"
                        )
            except Exception as e:
                # Log error but don't fail OCR processing
                logger.error(
                    f"Failed to persist OCR values to packet table for packet_id={packet_document.packet_id}: {e}",
                    exc_info=True
                )
        
        db.flush()
        
        logger.info(
            f"OCR processing completed: coversheet_page={coversheet_page_number}, "
            f"part_type={part_type}, total_pages={len(page_ocr_results)}"
        )
    
    def _process_portal_fields_from_payload(
        self,
        db: Session,
        packet_document: PacketDocumentDB,
        split_result: SplitResult,
        payload: Dict[str, Any]
    ) -> None:
        """
        Process Genzeon Portal: Extract fields from payload.ocr instead of OCR.
        
        Args:
            db: Database session
            packet_document: PacketDocumentDB instance to update
            split_result: SplitResult with pages (for coversheet page validation)
            payload: Full payload from integration.send_serviceops
        """
        logger.info(
            f"Processing Genzeon Portal fields from payload for document {packet_document.document_unique_identifier}"
        )
        
        # Check if already processed (idempotency)
        if packet_document.ocr_status == 'DONE':
            logger.info(
                f"Portal fields already extracted for document {packet_document.document_unique_identifier}, "
                f"skipping (likely concurrent processing)"
            )
            return
        
        # Set OCR status to IN_PROGRESS
        packet_document.ocr_status = 'IN_PROGRESS'
        db.flush()
        
        # Extract fields using channel strategy
        try:
            extracted_fields_payload = self.channel_strategy.extract_fields_from_payload(
                payload=payload,
                split_result=split_result
            )
        except ValueError as e:
            logger.error(f"Failed to extract fields from payload: {e}", exc_info=True)
            packet_document.ocr_status = 'FAILED'
            db.commit()
            raise DocumentProcessorError(f"Failed to extract fields from payload: {e}") from e
        
        # Get coversheet page and part type from strategy
        coversheet_page_number = self.channel_strategy.get_coversheet_page_number(
            payload=payload,
            split_result=split_result
        )
        part_type = self.channel_strategy.get_part_type(payload=payload)
        
        # Build ocr_metadata (simplified for Portal - no per-page OCR results)
        ocr_metadata_pages = []
        for page in split_result.pages:
            ocr_metadata_pages.append({
                'page_number': page.page_number,
                'fields': extracted_fields_payload.get('fields', {}) if page.page_number == coversheet_page_number else {},
                'duration_ms': 0,
                'overall_document_confidence': extracted_fields_payload.get('overall_document_confidence', 1.0) if page.page_number == coversheet_page_number else 0.0,
                'error': None,
                'status': 'skipped' if page.page_number != coversheet_page_number else 'from_payload'
            })
        
        ocr_metadata = {
            'version': 'v1',
            'pages': ocr_metadata_pages,
            'coversheet_page_number': coversheet_page_number,
            'part_type': part_type,
            'source': 'payload'  # Mark as from payload
        }
        
        # Update packet_document
        packet_document.ocr_metadata = ocr_metadata
        flag_modified(packet_document, 'ocr_metadata')
        packet_document.coversheet_page_number = coversheet_page_number
        packet_document.part_type = part_type
        
        # Normalize extracted_fields_payload before storing
        from app.utils.field_normalizer import FieldNormalizer
        normalized_payload = FieldNormalizer.normalize_extracted_fields(
            extracted_fields_payload, 
            source='PAYLOAD_INITIAL'
        )
        
        # Set extracted_fields (IMMUTABLE BASELINE) - normalized format
        packet_document.extracted_fields = normalized_payload
        flag_modified(packet_document, 'extracted_fields')
        
        # Set updated_extracted_fields (working copy) - use deepcopy to avoid shared references
        import copy
        packet_document.updated_extracted_fields = copy.deepcopy(normalized_payload)
        flag_modified(packet_document, 'updated_extracted_fields')
        
        # Update pages_metadata to mark coversheet
        if packet_document.pages_metadata:
            pages = packet_document.pages_metadata.get('pages', [])
            for page_meta in pages:
                if page_meta.get('page_number') == coversheet_page_number:
                    page_meta['is_coversheet'] = True
                    page_meta['ocr_confidence'] = extracted_fields_payload.get('overall_document_confidence', 1.0)
                    page_meta['ocr_status'] = 'from_payload'
                    flag_modified(packet_document, 'pages_metadata')
                    break
        
        # Update packet table with extracted values (same as OCR flow)
        # Get packet from relationship
        packet = db.query(PacketDB).filter(
            PacketDB.packet_id == packet_document.packet_id
        ).first()
        
        if packet and extracted_fields_payload.get('fields'):
            try:
                from app.utils.packet_converter import extract_from_ocr_fields
                
                # Extract beneficiary info from extracted fields
                beneficiary_last_name = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Beneficiary Last Name', 'beneficiaryLastName', 'beneficiary_last_name',
                        'Patient Last Name', 'patientLastName', 'patient_last_name',
                        'Member Last Name', 'memberLastName', 'member_last_name',
                        'Last Name', 'lastName', 'last_name', 'lname'
                    ]
                )
                beneficiary_first_name = extract_from_ocr_fields(
                    [packet_document],
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
                        [packet_document],
                        [
                            'Beneficiary Name', 'beneficiaryName', 'beneficiary_name',
                            'Patient Name', 'patientName', 'patient_name',
                            'Member Name', 'memberName', 'member_name',
                            'Full Name', 'fullName', 'full_name'
                        ]
                    )
                
                ocr_beneficiary_mbi = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Beneficiary Medicare ID',
                        'Medicare ID', 'medicareId', 'MBI', 'mbi', 'Beneficiary MBI', 'beneficiaryMbi',
                        'Medicare Beneficiary Identifier', 'Medicare Number', 'medicareNumber',
                        'HICN', 'hicn', 'Health Insurance Claim Number'
                    ]
                )
                
                # Extract provider info
                facility_name = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Facility Provider Name',
                        'Facility Name', 'facilityName', 'facility_name',
                        'Organization Name', 'organizationName', 'organization_name',
                        'Practice Name', 'practiceName', 'practice_name'
                    ]
                )
                physician_name = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Attending Physician Name',
                        'Physician Name', 'physicianName', 'physician_name',
                        'Ordering/Referring Physician Name', 'Ordering Physician Name',
                        'Referring Physician Name', 'Doctor Name', 'doctorName',
                        'Attending Physician', 'attendingPhysician'
                    ]
                )
                ocr_provider_name = facility_name or physician_name or extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Provider Name', 'providerName', 'provider_name',
                        'Rendering Provider Name', 'renderingProviderName',
                        'Billing Provider Name', 'billingProviderName'
                    ]
                )
                
                facility_npi = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Facility Provider NPI',
                        'Facility NPI', 'facilityNpi', 'facility_npi',
                        'Organization NPI', 'organizationNpi', 'organization_npi'
                    ]
                )
                physician_npi = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Attending Physician NPI',
                        'Physician NPI', 'physicianNpi', 'physician_npi',
                        'Ordering Physician NPI', 'orderingPhysicianNpi',
                        'Referring Physician NPI', 'referringPhysicianNpi'
                    ]
                )
                ocr_provider_npi = facility_npi or physician_npi
                
                # Extract submission type
                ocr_submission_type = extract_from_ocr_fields(
                    [packet_document],
                    [
                        'Submission Type', 'submissionType', 'submission_type',
                        'Priority', 'priority'
                    ]
                )
                
                # Normalize submission type
                # Uses partial matching (starts with) to handle values like 'expedited-initial', 'standard-initial'
                if ocr_submission_type:
                    submission_type_normalized = self._normalize_submission_type(ocr_submission_type)
                    if not submission_type_normalized:
                        logger.warning(
                            f"Unrecognized submission type from payload: {ocr_submission_type}, leaving as NULL for manual review"
                        )
                else:
                    # If no submission_type found, leave as None for manual review
                    submission_type_normalized = None
                
                # Update packet
                updated = False
                if ocr_beneficiary_name and (not packet.beneficiary_name or packet.beneficiary_name == "TBD"):
                    packet.beneficiary_name = ocr_beneficiary_name
                    updated = True
                if ocr_beneficiary_mbi and (not packet.beneficiary_mbi or packet.beneficiary_mbi == "TBD"):
                    packet.beneficiary_mbi = ocr_beneficiary_mbi
                    updated = True
                if ocr_provider_name and (not packet.provider_name or packet.provider_name == "TBD"):
                    packet.provider_name = ocr_provider_name
                    updated = True
                if ocr_provider_npi:
                    npi_clean = ''.join(filter(str.isdigit, str(ocr_provider_npi)))
                    if len(npi_clean) == 10:
                        if not packet.provider_npi or packet.provider_npi == "TBD":
                            packet.provider_npi = npi_clean
                            updated = True
                    else:
                        logger.warning(
                            f"Invalid NPI from payload: {ocr_provider_npi} "
                            f"(expected 10 digits, got {len(npi_clean)}). Not updating packet table."
                        )
                elif not packet.provider_npi or packet.provider_npi == "TBD":
                    # Keep as "TBD" since provider_npi is NOT NULL - will be manually reviewed
                    # Don't set to "0000000000" - leave as "TBD" for manual review
                    pass
                
                # Only update submission_type if we have a valid value
                if submission_type_normalized:
                    if not packet.submission_type or packet.submission_type != submission_type_normalized:
                        packet.submission_type = submission_type_normalized
                        packet.due_date = self._calculate_due_date(
                            packet.received_date,
                            submission_type=submission_type_normalized
                        )
                        updated = True
                # If submission_type is None, leave it as None for manual review
                # Don't set default - let someone manually review and set it
                
                if updated:
                    packet.updated_at = datetime.now(timezone.utc)
                    db.flush()
                    logger.info(
                        f"Updated packet {packet.external_id} with Portal-extracted values: "
                        f"beneficiary_name={ocr_beneficiary_name or 'unchanged'}, "
                        f"provider_name={ocr_provider_name or 'unchanged'}, "
                        f"provider_npi={'updated' if ocr_provider_npi else 'defaulted'}, "
                        f"submission_type={packet.submission_type or 'unchanged'}"
                    )
            except Exception as e:
                # Log error but don't fail Portal processing
                logger.error(
                    f"Failed to persist Portal values to packet table for packet_id={packet_document.packet_id}: {e}",
                    exc_info=True
                )
        
        # Mark OCR status as DONE
        packet_document.ocr_status = 'DONE'
        db.commit()
        
        logger.info(
            f"✓ Portal fields extracted from payload: coversheet_page={coversheet_page_number}, "
            f"part_type={part_type}, fields={len(extracted_fields_payload.get('fields', {}))}"
        )
    
    def _format_file_size(self, size_bytes: Optional[int]) -> str:
        """Format file size in bytes to human-readable string"""
        if size_bytes is None:
            return "Unknown"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f} MB"

