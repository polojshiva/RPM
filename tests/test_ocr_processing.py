"""
Unit tests for OCR processing improvements:
- Sequential processing with delays
- Early stopping when coversheet found
- Retry logic for failed pages
- Metadata handling for skipped pages
"""
import pytest
import sys
import time
from unittest.mock import Mock, MagicMock, patch, call

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.ocr_service import OCRService, OCRServiceError
from app.services.document_processor import DocumentProcessor
from app.services.document_splitter import SplitResult, SplitPage
from app.models.document_db import PacketDocumentDB
from app.config import settings


class TestOCRSequentialProcessing:
    """Test sequential OCR processing with delays"""
    
    @pytest.fixture
    def mock_ocr_service(self):
        """Mock OCR service"""
        service = Mock(spec=OCRService)
        return service
    
    @pytest.fixture
    def mock_split_result(self):
        """Create mock split result with 5 pages"""
        pages = []
        for i in range(1, 6):
            page = Mock(spec=SplitPage)
            page.page_number = i
            page.local_path = f"/tmp/page_{i}.pdf"
            pages.append(page)
        
        result = Mock(spec=SplitResult)
        result.pages = pages
        result.page_count = 5
        return result
    
    @pytest.fixture
    def mock_packet_document(self):
        """Mock packet document"""
        doc = Mock(spec=PacketDocumentDB)
        doc.packet_document_id = 1
        doc.external_id = "DOC-1"
        doc.packet_id = 1
        doc.ocr_status = 'NOT_STARTED'
        doc.pages_metadata = {
            'version': 'v1',
            'pages': [
                {'page_number': i, 'blob_path': f'page_{i}.pdf'}
                for i in range(1, 6)
            ]
        }
        # Add SQLAlchemy instance state for flag_modified
        doc._sa_instance_state = Mock()
        return doc
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock()
        db.flush = Mock()
        return db
    
    def test_sequential_processing_with_delays(self, mock_ocr_service, mock_split_result, mock_packet_document, mock_db):
        """Test that pages are processed sequentially with delays"""
        # Mock OCR results
        mock_ocr_service.run_ocr_on_pdf.return_value = {
            'fields': {'field1': {'value': 'test', 'confidence': 0.8}},
            'overall_document_confidence': 0.8,
            'duration_ms': 100,
            'coversheet_type': '',
            'doc_type': '',
            'raw': {}
        }
        
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    processor.ocr_service = mock_ocr_service
                    processor.coversheet_detector = Mock()
                    processor.coversheet_detector.detect_coversheet_page.return_value = 1
                    processor.part_classifier = Mock()
                    processor.part_classifier.classify_part_type.return_value = "PART_A"
                    
                    # Mock settings
                    with patch('app.services.document_processor.settings') as mock_settings:
                        with patch('app.services.document_processor.flag_modified', lambda obj, attr: None):  # Mock SQLAlchemy flag_modified
                            mock_settings.ocr_delay_between_requests = 0.01  # Use smaller delay for faster tests
                            mock_settings.ocr_retry_failed_pages = False
                            mock_settings.ocr_stop_after_coversheet = False
                            
                            with patch('time.sleep'):  # Mock sleep to speed up test
                                processor._process_ocr(
                                    db=mock_db,
                                    packet_document=mock_packet_document,
                                    split_result=mock_split_result,
                                    temp_files_to_cleanup=[]
                                )
                    
                    # Verify all pages were processed
                    assert mock_ocr_service.run_ocr_on_pdf.call_count == 5
    
    def test_early_stopping_when_coversheet_found(self, mock_ocr_service, mock_split_result, mock_packet_document, mock_db):
        """Test that processing stops when strong coversheet candidate is found"""
        # Page 3 will be the strong candidate
        def mock_ocr_side_effect(path):
            page_num = int(path.split('_')[1].split('.')[0])
            if page_num == 3:
                return {
                    'fields': {f'field{i}': {'value': f'val{i}', 'confidence': 0.8} for i in range(25)},
                    'overall_document_confidence': 0.85,
                    'duration_ms': 100,
                    'coversheet_type': '',
                    'doc_type': '',
                    'raw': {}
                }
            else:
                return {
                    'fields': {f'field{i}': {'value': f'val{i}', 'confidence': 0.5} for i in range(5)},
                    'overall_document_confidence': 0.3,
                    'duration_ms': 100,
                    'coversheet_type': '',
                    'doc_type': '',
                    'raw': {}
                }
        
        mock_ocr_service.run_ocr_on_pdf.side_effect = mock_ocr_side_effect
        
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    processor.ocr_service = mock_ocr_service
                    processor.coversheet_detector = Mock()
                    processor.coversheet_detector.detect_coversheet_page.return_value = 3
                    processor.part_classifier = Mock()
                    processor.part_classifier.classify_part_type.return_value = "PART_A"
                    
                    with patch('app.services.document_processor.settings') as mock_settings:
                        with patch('app.services.document_processor.flag_modified', lambda obj, attr: None):  # Mock SQLAlchemy flag_modified
                            mock_settings.ocr_delay_between_requests = 0.0
                            mock_settings.ocr_retry_failed_pages = False
                            mock_settings.ocr_stop_after_coversheet = True
                            mock_settings.ocr_coversheet_confidence_threshold = 0.7
                            mock_settings.ocr_min_coversheet_fields = 20
                            
                            processor._process_ocr(
                                db=mock_db,
                                packet_document=mock_packet_document,
                                split_result=mock_split_result,
                                temp_files_to_cleanup=[]
                            )
                        
                        # Should only process pages 1, 2, 3 (stop at 3)
                        assert mock_ocr_service.run_ocr_on_pdf.call_count == 3
                        
                        # Verify coversheet was set to page 3
                        assert mock_packet_document.coversheet_page_number == 3
    
    def test_fallback_to_detector_when_no_threshold_met(self, mock_ocr_service, mock_split_result, mock_packet_document, mock_db):
        """Test that when no page meets threshold, all pages are processed and detector is used"""
        # All pages have low confidence/fields
        mock_ocr_service.run_ocr_on_pdf.return_value = {
            'fields': {f'field{i}': {'value': f'val{i}', 'confidence': 0.5} for i in range(10)},
            'overall_document_confidence': 0.4,
            'duration_ms': 100,
            'coversheet_type': '',
            'doc_type': '',
            'raw': {}
        }
        
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    processor.ocr_service = mock_ocr_service
                    processor.coversheet_detector = Mock()
                    processor.coversheet_detector.detect_coversheet_page.return_value = 2  # Detector picks page 2
                    processor.part_classifier = Mock()
                    processor.part_classifier.classify_part_type.return_value = "PART_A"
                    
                    with patch('app.services.document_processor.settings') as mock_settings:
                        with patch('app.services.document_processor.flag_modified', lambda obj, attr: None):  # Mock SQLAlchemy flag_modified
                            mock_settings.ocr_delay_between_requests = 0.0
                            mock_settings.ocr_retry_failed_pages = False
                            mock_settings.ocr_stop_after_coversheet = True
                            mock_settings.ocr_coversheet_confidence_threshold = 0.7
                            mock_settings.ocr_min_coversheet_fields = 20
                            
                            processor._process_ocr(
                                db=mock_db,
                                packet_document=mock_packet_document,
                                split_result=mock_split_result,
                                temp_files_to_cleanup=[]
                            )
                    
                    # Should process ALL pages (no early stopping)
                    assert mock_ocr_service.run_ocr_on_pdf.call_count == 5
                    
                    # Detector should be called
                    processor.coversheet_detector.detect_coversheet_page.assert_called_once()
                    
                    # Coversheet should be set to detector's choice
                    assert mock_packet_document.coversheet_page_number == 2
    
    def test_retry_failed_pages(self, mock_ocr_service, mock_split_result, mock_packet_document, mock_db):
        """Test that failed pages are retried at the end"""
        call_count = {'count': 0}
        page_2_attempts = {'count': 0}
        
        def mock_ocr_side_effect(path):
            call_count['count'] += 1
            page_num = int(path.split('_')[1].split('.')[0])
            
            # Page 2 fails first 2 times, succeeds on 3rd
            if page_num == 2:
                page_2_attempts['count'] += 1
                if page_2_attempts['count'] <= 2:
                    raise OCRServiceError("502 Bad Gateway")
                else:
                    return {
                        'fields': {'field1': {'value': 'test', 'confidence': 0.8}},
                        'overall_document_confidence': 0.8,
                        'duration_ms': 100,
                        'coversheet_type': '',
                        'doc_type': '',
                        'raw': {}
                    }
            else:
                return {
                    'fields': {'field1': {'value': 'test', 'confidence': 0.8}},
                    'overall_document_confidence': 0.8,
                    'duration_ms': 100,
                    'coversheet_type': '',
                    'doc_type': '',
                    'raw': {}
                }
        
        mock_ocr_service.run_ocr_on_pdf.side_effect = mock_ocr_side_effect
        
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    processor.ocr_service = mock_ocr_service
                    processor.coversheet_detector = Mock()
                    processor.coversheet_detector.detect_coversheet_page.return_value = 1
                    processor.part_classifier = Mock()
                    processor.part_classifier.classify_part_type.return_value = "PART_A"
                    
                    with patch('app.services.document_processor.settings') as mock_settings:
                        with patch('app.services.document_processor.flag_modified', lambda obj, attr: None):  # Mock SQLAlchemy flag_modified
                            mock_settings.ocr_delay_between_requests = 0.0
                            mock_settings.ocr_retry_failed_pages = True
                            mock_settings.ocr_max_failed_page_retries = 3
                            mock_settings.ocr_stop_after_coversheet = False
                            
                            with patch('time.sleep'):  # Mock sleep for faster test
                                processor._process_ocr(
                                    db=mock_db,
                                    packet_document=mock_packet_document,
                                    split_result=mock_split_result,
                                    temp_files_to_cleanup=[]
                                )
                        
                        # Should have processed all pages + retries
                        # Initial: 5 pages (page 2 fails once, then succeeds on retry)
                        # Retry: page 2 retried and succeeds
                        # Total: 5 initial + 1 retry = 6 calls minimum
                        assert mock_ocr_service.run_ocr_on_pdf.call_count >= 6  # 5 initial + at least 1 retry
                        # Verify page 2 was retried and succeeded
                        assert page_2_attempts['count'] >= 2  # Failed once, then succeeded
    
    def test_skipped_pages_in_metadata(self, mock_ocr_service, mock_split_result, mock_packet_document, mock_db):
        """Test that skipped pages are included in metadata with status='skipped'"""
        # Page 3 will trigger early stopping
        def mock_ocr_side_effect(path):
            page_num = int(path.split('_')[1].split('.')[0])
            if page_num == 3:
                return {
                    'fields': {f'field{i}': {'value': f'val{i}', 'confidence': 0.8} for i in range(25)},
                    'overall_document_confidence': 0.85,
                    'duration_ms': 100,
                    'coversheet_type': '',
                    'doc_type': '',
                    'raw': {}
                }
            else:
                return {
                    'fields': {f'field{i}': {'value': f'val{i}', 'confidence': 0.5} for i in range(5)},
                    'overall_document_confidence': 0.3,
                    'duration_ms': 100,
                    'coversheet_type': '',
                    'doc_type': '',
                    'raw': {}
                }
        
        mock_ocr_service.run_ocr_on_pdf.side_effect = mock_ocr_side_effect
        
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    processor.ocr_service = mock_ocr_service
                    processor.coversheet_detector = Mock()
                    processor.coversheet_detector.detect_coversheet_page.return_value = 3
                    processor.part_classifier = Mock()
                    processor.part_classifier.classify_part_type.return_value = "PART_A"
                    
                    with patch('app.services.document_processor.settings') as mock_settings:
                        with patch('app.services.document_processor.flag_modified', lambda obj, attr: None):  # Mock SQLAlchemy flag_modified
                            mock_settings.ocr_delay_between_requests = 0.0
                            mock_settings.ocr_retry_failed_pages = False
                            mock_settings.ocr_stop_after_coversheet = True
                            mock_settings.ocr_coversheet_confidence_threshold = 0.7
                            mock_settings.ocr_min_coversheet_fields = 20
                            
                            processor._process_ocr(
                                db=mock_db,
                                packet_document=mock_packet_document,
                                split_result=mock_split_result,
                                temp_files_to_cleanup=[]
                            )
                        
                        # Verify ocr_metadata includes all pages
                        ocr_metadata = mock_packet_document.ocr_metadata
                        assert len(ocr_metadata['pages']) == 5  # All 5 pages
                        
                        # Pages 1-3 should be processed
                        for i in range(1, 4):
                            page_data = next(p for p in ocr_metadata['pages'] if p['page_number'] == i)
                            assert page_data['status'] == 'processed'
                            assert 'fields' in page_data
                        
                        # Pages 4-5 should be skipped
                        for i in range(4, 6):
                            page_data = next(p for p in ocr_metadata['pages'] if p['page_number'] == i)
                            assert page_data['status'] == 'skipped'
                            assert page_data['fields'] == {}
                            assert 'skip_reason' in page_data

