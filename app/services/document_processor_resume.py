"""
Document Processor Resume Logic
Implements resume-on-retry using existing DB fields as checkpoints.
No schema changes required.
"""
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.services.db import get_db_session
from app.services.payload_parser import PayloadParser
from app.services.document_splitter import DocumentSplitter, SplitResult
from app.services.blob_storage import BlobStorageClient, BlobStorageError
from app.services.ocr_service import OCRService
from app.services.pdf_merger import PDFMerger, PDFMergeError
from app.utils.path_builder import build_consolidated_paths, build_page_blob_path
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.config import settings

logger = logging.getLogger(__name__)


class ResumeState:
    """State information for resuming processing"""
    def __init__(
        self,
        packet: PacketDB,
        packet_document: PacketDocumentDB,
        can_resume: bool,
        resume_from: Optional[str] = None
    ):
        self.packet = packet
        self.packet_document = packet_document
        self.can_resume = can_resume
        self.resume_from = resume_from  # 'ocr', 'split', 'merge', 'download', None


def check_resume_state(
    db: Session,
    decision_tracking_id: str,
    packet_id: Optional[int] = None
) -> Optional[ResumeState]:
    """
    Check if processing can be resumed from existing state.
    
    Uses existing DB fields as checkpoints:
    - ocr_status == 'DONE' → fully processed, no resume needed
    - split_status == 'DONE' and pages_metadata exists → resume from OCR
    - consolidated_blob_path exists → resume from split
    - packet_document exists → resume from merge/download
    
    Args:
        db: Database session
        decision_tracking_id: Decision tracking ID
        packet_id: Optional packet ID (if known)
        
    Returns:
        ResumeState if resume is possible, None otherwise
    """
    # Find packet
    if packet_id:
        packet = db.query(PacketDB).filter(PacketDB.packet_id == packet_id).first()
    else:
        packet = db.query(PacketDB).filter(
            PacketDB.decision_tracking_id == decision_tracking_id
        ).first()
    
    if not packet:
        return None
    
    # Find document
    packet_document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    if not packet_document:
        return None
    
    # Check resume state - Decision Tree
    
    # 1. If ocr_status == 'DONE' → fully processed, no resume needed
    if packet_document.ocr_status == 'DONE':
        logger.info(
            f"Document already fully processed: packet_id={packet.packet_id}, "
            f"packet_document_id={packet_document.packet_document_id}"
        )
        return ResumeState(
            packet=packet,
            packet_document=packet_document,
            can_resume=False,
            resume_from=None
        )
    
    # 2. If split_status == 'DONE' and pages_metadata exists → validate and resume from OCR
    if (packet_document.split_status == 'DONE' and 
        packet_document.pages_metadata):
        
        pages = packet_document.pages_metadata.get('pages', [])
        
        # Guard 1: pages_metadata.pages must exist and not be empty
        if not pages or len(pages) == 0:
            logger.warning(
                f"split_status=DONE but pages_metadata.pages is empty for packet_id={packet.packet_id} - "
                f"treating as needs split (partial write detected)"
            )
            return ResumeState(
                packet=packet,
                packet_document=packet_document,
                can_resume=True,
                resume_from='split'  # Re-split to rebuild pages_metadata
            )
        
        # Guard 2: Validate each page entry has required fields
        invalid_pages = []
        for page in pages:
            page_num = page.get('page_number')
            blob_path = page.get('blob_path') or page.get('relative_path')
            
            # Must have page_number (integer)
            if not isinstance(page_num, int) or page_num < 1:
                invalid_pages.append(f"page missing/invalid page_number: {page}")
                continue
            
            # Must have non-empty blob_path or relative_path (string)
            if not blob_path or not isinstance(blob_path, str) or len(blob_path.strip()) == 0:
                invalid_pages.append(f"page {page_num} missing/invalid blob_path")
        
        if invalid_pages:
            logger.warning(
                f"split_status=DONE but {len(invalid_pages)} page(s) have invalid metadata "
                f"for packet_id={packet.packet_id} - treating as needs split (partial write detected). "
                f"Invalid pages: {invalid_pages[:3]}"  # Log first 3 only
            )
            return ResumeState(
                packet=packet,
                packet_document=packet_document,
                can_resume=True,
                resume_from='split'  # Re-split to rebuild pages_metadata
            )
        
        # All validations passed - can resume from OCR
        # Allow ocr_status='IN_PROGRESS' to resume (worker may have died mid-OCR)
        ocr_status = packet_document.ocr_status
        if ocr_status in ('NOT_STARTED', 'IN_PROGRESS', 'FAILED'):
            logger.info(
                f"Can resume from OCR: packet_id={packet.packet_id}, "
                f"split_status={packet_document.split_status}, "
                f"ocr_status={ocr_status}, "
                f"pages={len(pages)} (all validated)"
            )
            return ResumeState(
                packet=packet,
                packet_document=packet_document,
                can_resume=True,
                resume_from='ocr'
            )
        else:
            # ocr_status is something unexpected - log and treat as needs OCR
            logger.warning(
                f"split_status=DONE with valid pages_metadata but unexpected ocr_status='{ocr_status}' "
                f"for packet_id={packet.packet_id} - treating as needs OCR"
            )
            return ResumeState(
                packet=packet,
                packet_document=packet_document,
                can_resume=True,
                resume_from='ocr'
            )
    
    if packet_document.consolidated_blob_path:
        # Can resume from split
        logger.info(
            f"Can resume from split: packet_id={packet.packet_id}, "
            f"consolidated_blob_path={packet_document.consolidated_blob_path}"
        )
        return ResumeState(
            packet=packet,
            packet_document=packet_document,
            can_resume=True,
            resume_from='split'
        )
    
    if packet_document.packet_document_id:
        # Can resume from merge/download
        logger.info(
            f"Can resume from merge: packet_id={packet.packet_id}, "
            f"packet_document_id={packet_document.packet_document_id}"
        )
        return ResumeState(
            packet=packet,
            packet_document=packet_document,
            can_resume=True,
            resume_from='merge'
        )
    
    # No resume state
    return None


def get_page_blob_paths_from_metadata(packet_document: PacketDocumentDB) -> Dict[int, str]:
    """
    Extract page blob paths from pages_metadata.
    
    Args:
        packet_document: PacketDocumentDB instance
        
    Returns:
        Dict mapping page_number to blob_path
    """
    if not packet_document.pages_metadata:
        return {}
    
    pages = packet_document.pages_metadata.get('pages', [])
    result = {}
    
    for page in pages:
        page_num = page.get('page_number')
        blob_path = page.get('blob_path') or page.get('relative_path')
        if page_num and blob_path:
            result[page_num] = blob_path
    
    return result

