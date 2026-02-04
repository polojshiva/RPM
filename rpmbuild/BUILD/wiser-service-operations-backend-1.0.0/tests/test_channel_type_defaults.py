"""
Unit tests for channel_type_id default behavior (NULL/empty -> ESMD)
Tests that NULL, 0, or empty channel_type_id defaults to ESMD (3)
"""
import pytest
import sys
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.models.channel_type import ChannelType
from app.services.channel_processing_strategy import get_channel_strategy, ESMDProcessingStrategy
from app.services.document_processor import DocumentProcessor
from app.services.message_poller import MessagePollerService
from app.models.integration_db import SendServiceOpsDB


class TestChannelTypeDefaults:
    """Test that NULL/empty channel_type_id defaults to ESMD (3)"""
    
    def test_get_channel_strategy_none_defaults_to_esmd(self):
        """Test get_channel_strategy(None) returns ESMD"""
        strategy = get_channel_strategy(None)
        assert isinstance(strategy, ESMDProcessingStrategy)
        assert strategy.should_run_ocr() is True
    
    def test_get_channel_strategy_zero_defaults_to_esmd(self):
        """Test get_channel_strategy(0) returns ESMD"""
        strategy = get_channel_strategy(0)
        assert isinstance(strategy, ESMDProcessingStrategy)
        assert strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_document_processor_none_defaults_to_esmd(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger
    ):
        """Test DocumentProcessor with None channel_type_id defaults to ESMD"""
        processor = DocumentProcessor(channel_type_id=None)
        assert processor.channel_type_id is None  # Stored as None
        assert isinstance(processor.channel_strategy, ESMDProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_document_processor_zero_defaults_to_esmd(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger
    ):
        """Test DocumentProcessor with 0 channel_type_id defaults to ESMD"""
        processor = DocumentProcessor(channel_type_id=0)
        assert processor.channel_type_id == 0  # Stored as 0
        assert isinstance(processor.channel_strategy, ESMDProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_document_processor_message_with_none_channel_type_id(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger
    ):
        """Test DocumentProcessor processes message with None channel_type_id as ESMD"""
        # Create mock message with None channel_type_id
        mock_message = Mock(spec=SendServiceOpsDB)
        mock_message.message_id = 100
        mock_message.channel_type_id = None
        mock_message.payload = {
            'documents': [],
            'decision_tracking_id': 'test-uuid'
        }
        mock_message.created_at = datetime(2026, 1, 1)
        
        # Create processor without channel_type_id
        processor = DocumentProcessor(channel_type_id=None)
        
        # When processing, it should default to ESMD
        # Check that strategy is ESMD after message processing logic would run
        # (We can't fully test process_message without DB, but we can test the strategy selection)
        assert isinstance(processor.channel_strategy, ESMDProcessingStrategy)
    
    @pytest.mark.asyncio
    @patch('app.services.message_poller.DocumentProcessor')
    @patch('app.services.message_poller.PayloadParser')
    @patch('app.services.message_poller.IntegrationInboxService')
    async def test_message_poller_none_channel_type_id_defaults_to_esmd(
        self,
        mock_inbox_service_class,
        mock_payload_parser,
        mock_document_processor_class
    ):
        """Test MessagePoller defaults None channel_type_id to ESMD"""
        poller = MessagePollerService()
        
        # Create mock message with None channel_type_id
        mock_message = Mock(spec=SendServiceOpsDB)
        mock_message.message_id = 100
        mock_message.channel_type_id = None
        mock_message.payload = {'documents': []}
        
        # Mock PayloadParser
        mock_parsed = MagicMock()
        mock_parsed.decision_tracking_id = "test-uuid"
        mock_parsed.unique_id = "test-unique"
        mock_parsed.esmd_transaction_id = None
        mock_parsed.documents = []
        mock_parsed.message_type = "ingest_file_package"
        mock_parsed.blob_storage_path = None
        mock_parsed.extraction_path = None
        mock_payload_parser.parse_full_payload.return_value = mock_parsed
        
        # Mock DocumentProcessor
        mock_processor = MagicMock()
        mock_document_processor_class.return_value = mock_processor
        
        # Mock inbox service
        mock_inbox_service = MagicMock()
        mock_inbox_service_class.return_value = mock_inbox_service
        
        # Process message with None channel_type_id
        await poller._process_message(mock_message, inbox_id=123, channel_type_id=None)
        
        # Verify DocumentProcessor was created with ESMD (3)
        mock_document_processor_class.assert_called_once_with(
            channel_type_id=ChannelType.ESMD  # Should default to 3
        )
    
    @pytest.mark.asyncio
    @patch('app.services.message_poller.DocumentProcessor')
    @patch('app.services.message_poller.PayloadParser')
    @patch('app.services.message_poller.IntegrationInboxService')
    async def test_message_poller_zero_channel_type_id_defaults_to_esmd(
        self,
        mock_inbox_service_class,
        mock_payload_parser,
        mock_document_processor_class
    ):
        """Test MessagePoller defaults 0 channel_type_id to ESMD"""
        poller = MessagePollerService()
        
        # Create mock message with 0 channel_type_id
        mock_message = Mock(spec=SendServiceOpsDB)
        mock_message.message_id = 101
        mock_message.channel_type_id = 0
        mock_message.payload = {'documents': []}
        
        # Mock PayloadParser
        mock_parsed = MagicMock()
        mock_parsed.decision_tracking_id = "test-uuid"
        mock_parsed.unique_id = "test-unique"
        mock_parsed.esmd_transaction_id = None
        mock_parsed.documents = []
        mock_parsed.message_type = "ingest_file_package"
        mock_parsed.blob_storage_path = None
        mock_parsed.extraction_path = None
        mock_payload_parser.parse_full_payload.return_value = mock_parsed
        
        # Mock DocumentProcessor
        mock_processor = MagicMock()
        mock_document_processor_class.return_value = mock_processor
        
        # Mock inbox service
        mock_inbox_service = MagicMock()
        mock_inbox_service_class.return_value = mock_inbox_service
        
        # Process message with 0 channel_type_id
        await poller._process_message(mock_message, inbox_id=124, channel_type_id=0)
        
        # Verify DocumentProcessor was created with ESMD (3)
        mock_document_processor_class.assert_called_once_with(
            channel_type_id=ChannelType.ESMD  # Should default to 3
        )

