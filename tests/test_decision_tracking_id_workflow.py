"""
Integration/workflow tests for decision_tracking_id migration:
- End-to-end packet creation with decision_tracking_id
- Idempotency across multiple message processing
- Blob path generation uses decision_tracking_id
"""
import pytest
import sys
from unittest.mock import Mock, MagicMock, patch

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from datetime import datetime, timezone
from app.services.document_processor import DocumentProcessor
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.utils.path_builder import build_consolidated_paths


class TestDecisionTrackingIdWorkflow:
    """Test decision_tracking_id workflow end-to-end"""
    
    @pytest.fixture
    def sample_message(self):
        """Create sample message with decision_tracking_id"""
        message = Mock(spec=SendServiceOpsDB)
        message.message_id = 123
        message.decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        message.payload = {
            'decision_tracking_id': '550e8400-e29b-41d4-a716-446655440000',
            'unique_id': 'unique-123',
            'esmd_transaction_id': 'esmd-456',
            'submission_metadata': {
                'submission_date': '2026-01-15T12:00:00Z'
            },
            'documents': [
                {
                    'file_name': 'test.pdf',
                    'source_absolute_url': 'https://storage/test.pdf',
                    'mime_type': 'application/pdf',
                    'file_size': 1000,
                    'document_unique_id': 'DOC-123',
                    'documentUniqueIdentifier': 'DOC-123',
                    'document_unique_identifier': 'DOC-123'
                }
            ],
            'numberOfDocuments': 1
        }
        message.created_at = datetime.now(timezone.utc)
        return message
    
    def test_blob_path_uses_decision_tracking_id(self):
        """Test that blob paths use decision_tracking_id (not case_id)"""
        decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        packet_id = 123
        dt_utc = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        paths = build_consolidated_paths(
            decision_tracking_id=decision_tracking_id,
            packet_id=packet_id,
            dt_utc=dt_utc
        )
        
        # Verify path uses decision_tracking_id
        assert decision_tracking_id in paths.processing_root_path
        assert decision_tracking_id in paths.consolidated_pdf_blob_path
        assert f"service_ops_processing/2026/01-15/{decision_tracking_id}" in paths.processing_root_path
    
    def test_packet_creation_sets_decision_tracking_id(self, sample_message):
        """Test that packet creation sets decision_tracking_id correctly"""
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    
                    # Mock all dependencies
                    with patch.object(processor, '_get_or_create_packet') as mock_get_packet:
                        with patch.object(processor, '_get_or_create_consolidated_document'):
                            with patch.object(processor, 'blob_client'):
                                with patch.object(processor, 'pdf_merger'):
                                    with patch.object(processor, 'splitter'):
                                        with patch.object(processor, 'ocr_service', None):
                                            with patch('app.services.document_processor.get_db_session') as mock_db_session:
                                                mock_db = Mock()
                                                mock_db_session.return_value.__enter__.return_value = mock_db
                                                
                                                # Mock packet creation
                                                mock_packet = Mock(spec=PacketDB)
                                                mock_packet.packet_id = 123
                                                mock_packet.external_id = "PKT-2026-123456"
                                                mock_packet.decision_tracking_id = sample_message.decision_tracking_id
                                                mock_get_packet.return_value = mock_packet
                                                
                                                # Process message
                                                processor.process_message(sample_message)
                                                
                                                # Verify _get_or_create_packet was called with decision_tracking_id
                                                mock_get_packet.assert_called_once()
                                                call_args = mock_get_packet.call_args
                                                assert call_args[1]['decision_tracking_id'] == sample_message.decision_tracking_id
    
    def test_idempotency_same_decision_tracking_id(self, sample_message):
        """Test that processing same decision_tracking_id twice returns same packet"""
        # Mock DocumentProcessor initialization
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    processor = DocumentProcessor()
                    
                    # Mock packet
                    mock_packet = Mock(spec=PacketDB)
                    mock_packet.packet_id = 123
                    mock_packet.external_id = "PKT-2026-123456"
                    mock_packet.decision_tracking_id = sample_message.decision_tracking_id
                    
                    call_count = {'count': 0}
                    
                    def mock_get_packet_side_effect(*args, **kwargs):
                        call_count['count'] += 1
                        if call_count['count'] == 1:
                            # First call: create new packet
                            mock_packet.packet_id = 123
                            return mock_packet
                        else:
                            # Second call: return existing packet
                            return mock_packet
                    
                        with patch.object(processor, '_get_or_create_packet', side_effect=mock_get_packet_side_effect):
                            with patch.object(processor, '_get_or_create_consolidated_document'):
                                with patch.object(processor, 'blob_client'):
                                    with patch.object(processor, 'pdf_merger'):
                                        with patch.object(processor, 'splitter'):
                                            with patch.object(processor, 'ocr_service', None):
                                                with patch('app.services.document_processor.get_db_session') as mock_db_session:
                                                    mock_db = Mock()
                                                    mock_db_session.return_value.__enter__.return_value = mock_db
                                                    
                                                    # Process message twice
                                                    processor.process_message(sample_message)
                                                    processor.process_message(sample_message)
                                                    
                                                    # Verify _get_or_create_packet was called twice
                                                    assert call_count['count'] == 2
                                                    # Both calls should return same packet_id
                                                    # (verified by same mock_packet being returned)

