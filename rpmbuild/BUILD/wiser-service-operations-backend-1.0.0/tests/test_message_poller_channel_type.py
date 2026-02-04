"""
Unit tests for Phase 3: MessagePoller with channel_type_id support
Tests MessagePoller integration with channel_type_id
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
from app.models.integration_db import SendServiceOpsDB
from app.services.message_poller import MessagePollerService


class TestMessagePollerChannelType:
    """Test MessagePollerService with channel_type_id"""
    
    @pytest.fixture
    def poller_service(self):
        """Create MessagePollerService instance"""
        return MessagePollerService()
    
    @pytest.fixture
    def sample_messages(self):
        """Sample messages with different channel_type_id values"""
        return [
            {
                'message_id': 270,
                'decision_tracking_id': '04eb1038-f6cf-4359-81a0-cee8468fa3bb',
                'payload': {'documents': []},
                'created_at': datetime(2026, 1, 6),
                'channel_type_id': ChannelType.ESMD  # 3
            },
            {
                'message_id': 271,
                'decision_tracking_id': 'e7b8c1e2-1234-4cde-9abc-1234567890ab',
                'payload': {'documents': []},
                'created_at': datetime(2026, 1, 6),
                'channel_type_id': ChannelType.GENZEON_FAX  # 2
            },
            {
                'message_id': 272,
                'decision_tracking_id': 'b1c2d3e4-5678-4abc-9def-234567890abc',
                'payload': {'documents': []},
                'created_at': datetime(2026, 1, 6),
                'channel_type_id': ChannelType.GENZEON_PORTAL  # 1
            },
            {
                'message_id': 100,
                'decision_tracking_id': 'old-uuid',
                'payload': {'documents': []},
                'created_at': datetime(2026, 1, 1),
                'channel_type_id': None  # Backward compatibility
            }
        ]
    
    @pytest.mark.asyncio
    @patch('app.services.message_poller.IntegrationInboxService')
    async def test_poll_and_process_passes_channel_type_id(
        self,
        mock_inbox_service_class,
        poller_service,
        sample_messages
    ):
        """Test _poll_and_process passes channel_type_id to insert_into_inbox"""
        # Mock inbox service
        mock_inbox_service = MagicMock()
        mock_inbox_service_class.return_value = mock_inbox_service
        mock_inbox_service.poll_new_messages.return_value = sample_messages
        mock_inbox_service.insert_into_inbox.return_value = 123  # inbox_id
        mock_inbox_service.update_watermark.return_value = None
        
        # Mock _process_claimed_jobs to avoid actual processing
        poller_service._process_claimed_jobs = AsyncMock()
        
        await poller_service._poll_and_process()
        
        # Verify insert_into_inbox was called with channel_type_id for each message
        assert mock_inbox_service.insert_into_inbox.call_count == 4
        
        # Check first call (ESMD)
        call_args_esmd = mock_inbox_service.insert_into_inbox.call_args_list[0]
        assert call_args_esmd[0][4] == ChannelType.ESMD  # channel_type_id parameter
        
        # Check second call (Fax)
        call_args_fax = mock_inbox_service.insert_into_inbox.call_args_list[1]
        assert call_args_fax[0][4] == ChannelType.GENZEON_FAX
        
        # Check third call (Portal)
        call_args_portal = mock_inbox_service.insert_into_inbox.call_args_list[2]
        assert call_args_portal[0][4] == ChannelType.GENZEON_PORTAL
        
        # Check fourth call (None - backward compatibility)
        call_args_none = mock_inbox_service.insert_into_inbox.call_args_list[3]
        assert call_args_none[0][4] is None
    
    @pytest.mark.asyncio
    @patch('app.services.message_poller.DocumentProcessor')
    @patch('app.services.message_poller.PayloadParser')
    @patch('app.services.message_poller.IntegrationInboxService')
    async def test_process_message_with_channel_type_id(
        self,
        mock_inbox_service_class,
        mock_payload_parser,
        mock_document_processor_class,
        poller_service
    ):
        """Test _process_message passes channel_type_id to DocumentProcessor"""
        # Create mock message
        mock_message = MagicMock(spec=SendServiceOpsDB)
        mock_message.message_id = 270
        mock_message.channel_type_id = ChannelType.ESMD
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
        
        await poller_service._process_message(
            mock_message,
            inbox_id=123,
            channel_type_id=ChannelType.ESMD
        )
        
        # Verify DocumentProcessor was created with channel_type_id
        mock_document_processor_class.assert_called_once_with(
            channel_type_id=ChannelType.ESMD
        )
        
        # Verify process_message was called
        mock_processor.process_message.assert_called_once_with(
            mock_message,
            inbox_id=123
        )
    
    @pytest.mark.asyncio
    @patch('app.services.message_poller.DocumentProcessor')
    @patch('app.services.message_poller.PayloadParser')
    @patch('app.services.message_poller.IntegrationInboxService')
    async def test_process_message_fallback_to_message_channel_type_id(
        self,
        mock_inbox_service_class,
        mock_payload_parser,
        mock_document_processor_class,
        poller_service
    ):
        """Test _process_message falls back to message.channel_type_id if not provided"""
        # Create mock message with channel_type_id
        mock_message = MagicMock(spec=SendServiceOpsDB)
        mock_message.message_id = 272
        mock_message.channel_type_id = ChannelType.GENZEON_PORTAL
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
        
        # Call without channel_type_id parameter (should fallback to message.channel_type_id)
        await poller_service._process_message(
            mock_message,
            inbox_id=124
            # channel_type_id not provided
        )
        
        # Verify DocumentProcessor was created with message.channel_type_id
        mock_document_processor_class.assert_called_once_with(
            channel_type_id=ChannelType.GENZEON_PORTAL
        )
    
    @pytest.mark.asyncio
    @patch('app.services.message_poller.DocumentProcessor')
    @patch('app.services.message_poller.PayloadParser')
    @patch('app.services.message_poller.IntegrationInboxService')
    async def test_process_claimed_jobs_passes_channel_type_id(
        self,
        mock_inbox_service_class,
        mock_payload_parser,
        mock_document_processor_class,
        poller_service
    ):
        """Test _process_claimed_jobs passes channel_type_id from job to _process_message"""
        # Mock inbox service
        mock_inbox_service = MagicMock()
        mock_inbox_service_class.return_value = mock_inbox_service
        
        # Mock claim_job to return job with channel_type_id
        mock_job = {
            'inbox_id': 123,
            'message_id': 270,
            'decision_tracking_id': 'test-uuid',
            'message_type': 'ingest_file_package',
            'status': 'PROCESSING',
            'attempt_count': 1,
            'channel_type_id': ChannelType.ESMD
        }
        mock_inbox_service.claim_job.return_value = mock_job
        
        # Mock get_source_message
        mock_message = MagicMock(spec=SendServiceOpsDB)
        mock_message.message_id = 270
        mock_message.channel_type_id = ChannelType.ESMD
        mock_message.payload = {'documents': []}
        mock_inbox_service.get_source_message.return_value = mock_message
        
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
        
        # Mock status_update_service
        poller_service.status_update_service = MagicMock()
        poller_service.status_update_service.mark_done_with_retry.return_value = MagicMock(
            success=True,
            attempts=1
        )
        
        # Mock _process_message to capture channel_type_id and message_type_id
        captured_channel_type_id = None
        captured_message_type_id = None
        
        async def capture_process_message(message, inbox_id, channel_type_id=None, message_type_id=None):
            nonlocal captured_channel_type_id, captured_message_type_id
            captured_channel_type_id = channel_type_id
            captured_message_type_id = message_type_id
        
        poller_service._process_message = AsyncMock(side_effect=capture_process_message)
        
        await poller_service._process_claimed_jobs()
        
        # Verify channel_type_id was passed from job to _process_message
        assert captured_channel_type_id == ChannelType.ESMD

