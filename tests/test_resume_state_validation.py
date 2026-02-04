"""
Unit tests for check_resume_state validation logic
Tests guards against partial metadata and resume decision tree.
"""
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock

# Mock Azure modules before importing (same pattern as other tests)
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.document_processor_resume import check_resume_state, ResumeState
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB


class TestResumeStateValidation:
    """Test resume state validation and guards"""
    
    @pytest.fixture
    def mock_packet(self):
        """Create mock packet"""
        packet = MagicMock(spec=PacketDB)
        packet.packet_id = 1
        packet.decision_tracking_id = "test-decision-id"
        packet.external_id = "PKT-2025-1"
        return packet
    
    @pytest.fixture
    def mock_packet_document(self, mock_packet):
        """Create mock packet_document"""
        doc = MagicMock(spec=PacketDocumentDB)
        doc.packet_document_id = 1
        doc.packet_id = mock_packet.packet_id
        doc.ocr_status = 'NOT_STARTED'
        doc.split_status = 'NOT_STARTED'
        doc.consolidated_blob_path = None
        doc.pages_metadata = None
        return doc
    
    @pytest.fixture
    def mock_db_session(self, mock_packet, mock_packet_document):
        """Create mock database session"""
        session = MagicMock()
        
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = mock_packet
        
        # Mock document query
        doc_query = MagicMock()
        doc_query.filter.return_value.first.return_value = mock_packet_document
        
        session.query.side_effect = lambda model: {
            PacketDB: packet_query,
            PacketDocumentDB: doc_query
        }[model]
        
        return session
    
    def test_ocr_status_done_no_resume(self, mock_db_session, mock_packet, mock_packet_document):
        """Test ocr_status='DONE' → can_resume=False"""
        mock_packet_document.ocr_status = 'DONE'
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is False
        assert result.resume_from is None
        assert result.packet.packet_id == mock_packet.packet_id
    
    def test_split_status_done_pages_metadata_empty_resume_from_split(self, mock_db_session, mock_packet, mock_packet_document):
        """Test split_status='DONE' but pages_metadata.pages is empty → resume_from='split'"""
        mock_packet_document.split_status = 'DONE'
        mock_packet_document.pages_metadata = {'version': 'v1', 'pages': []}  # Empty list
        mock_packet_document.consolidated_blob_path = None  # No consolidated blob
        mock_packet_document.ocr_status = 'NOT_STARTED'
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        # When pages_metadata.pages is empty list, the condition `pages_metadata.get('pages')` is truthy
        # but then the guard checks `if not pages or len(pages) == 0` and returns 'split'
        assert result.resume_from == 'split'
    
    def test_split_status_done_pages_metadata_missing_blob_paths_resume_from_split(self, mock_db_session, mock_packet, mock_packet_document):
        """Test split_status='DONE' but pages missing blob_path → resume_from='split'"""
        mock_packet_document.split_status = 'DONE'
        mock_packet_document.pages_metadata = {
            'version': 'v1',
            'pages': [
                {'page_number': 1, 'blob_path': 'path1.pdf'},  # Valid
                {'page_number': 2},  # Missing blob_path
                {'page_number': 3, 'blob_path': ''}  # Empty blob_path
            ]
        }
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'split'
    
    def test_split_status_done_valid_pages_ocr_not_started_resume_from_ocr(self, mock_db_session, mock_packet, mock_packet_document):
        """Test split_status='DONE' with valid pages + ocr_status='NOT_STARTED' → resume_from='ocr'"""
        mock_packet_document.split_status = 'DONE'
        mock_packet_document.ocr_status = 'NOT_STARTED'
        mock_packet_document.pages_metadata = {
            'version': 'v1',
            'pages': [
                {'page_number': 1, 'blob_path': 'path1.pdf'},
                {'page_number': 2, 'blob_path': 'path2.pdf'},
                {'page_number': 3, 'relative_path': 'path3.pdf'}  # relative_path also valid
            ]
        }
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'ocr'
    
    def test_split_status_done_valid_pages_ocr_in_progress_resume_from_ocr(self, mock_db_session, mock_packet, mock_packet_document):
        """Test split_status='DONE' with valid pages + ocr_status='IN_PROGRESS' → resume_from='ocr'"""
        mock_packet_document.split_status = 'DONE'
        mock_packet_document.ocr_status = 'IN_PROGRESS'  # Worker died mid-OCR
        mock_packet_document.pages_metadata = {
            'version': 'v1',
            'pages': [
                {'page_number': 1, 'blob_path': 'path1.pdf'},
                {'page_number': 2, 'blob_path': 'path2.pdf'}
            ]
        }
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'ocr'  # Can resume from OCR even if IN_PROGRESS
    
    def test_split_status_done_valid_pages_ocr_failed_resume_from_ocr(self, mock_db_session, mock_packet, mock_packet_document):
        """Test split_status='DONE' with valid pages + ocr_status='FAILED' → resume_from='ocr'"""
        mock_packet_document.split_status = 'DONE'
        mock_packet_document.ocr_status = 'FAILED'
        mock_packet_document.pages_metadata = {
            'version': 'v1',
            'pages': [
                {'page_number': 1, 'blob_path': 'path1.pdf'},
                {'page_number': 2, 'blob_path': 'path2.pdf'}
            ]
        }
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'ocr'  # Can retry OCR
    
    def test_split_status_done_invalid_page_number_resume_from_split(self, mock_db_session, mock_packet, mock_packet_document):
        """Test split_status='DONE' but page_number is invalid → resume_from='split'"""
        mock_packet_document.split_status = 'DONE'
        mock_packet_document.pages_metadata = {
            'version': 'v1',
            'pages': [
                {'page_number': 1, 'blob_path': 'path1.pdf'},  # Valid
                {'page_number': 0, 'blob_path': 'path2.pdf'},  # Invalid (must be >= 1)
                {'page_number': 'invalid', 'blob_path': 'path3.pdf'},  # Invalid (not int)
                {}  # Missing page_number
            ]
        }
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'split'  # Invalid metadata → re-split
    
    def test_consolidated_blob_path_exists_resume_from_split(self, mock_db_session, mock_packet, mock_packet_document):
        """Test consolidated_blob_path exists → resume_from='split'"""
        mock_packet_document.consolidated_blob_path = 'service_ops_processing/2025/01-15/test-id/consolidated.pdf'
        mock_packet_document.split_status = 'NOT_STARTED'
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'split'
    
    def test_packet_document_exists_resume_from_merge(self, mock_db_session, mock_packet, mock_packet_document):
        """Test packet_document exists but no consolidated_blob_path → resume_from='merge'"""
        mock_packet_document.consolidated_blob_path = None
        mock_packet_document.split_status = 'NOT_STARTED'
        mock_packet_document.packet_document_id = 1
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is not None
        assert result.can_resume is True
        assert result.resume_from == 'merge'
    
    def test_no_packet_no_resume(self, mock_db_session):
        """Test no packet found → None"""
        from app.models.packet_db import PacketDB
        
        # Mock packet query to return None
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            else:
                return MagicMock()  # Return mock for other models
        
        mock_db_session.query.side_effect = query_side_effect
        
        result = check_resume_state(mock_db_session, "nonexistent-decision-id")
        
        assert result is None
    
    def test_no_packet_document_no_resume(self, mock_db_session, mock_packet):
        """Test packet exists but no packet_document → None"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = mock_packet
        
        # Mock document query to return None
        doc_query = MagicMock()
        doc_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDocumentDB:
                return doc_query
        
        mock_db_session.query.side_effect = query_side_effect
        
        result = check_resume_state(mock_db_session, "test-decision-id")
        
        assert result is None

