"""
Unit tests for Phase 1: Channel Type Support
Tests database schema, models, and IntegrationInboxService updates
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from sqlalchemy import text

from app.models.channel_type import ChannelType
from app.models.integration_db import SendServiceOpsDB
from app.services.integration_inbox import IntegrationInboxService


class TestChannelTypeEnum:
    """Test ChannelType enum"""
    
    def test_channel_type_values(self):
        """Test ChannelType enum has correct values"""
        assert ChannelType.GENZEON_PORTAL == 1
        assert ChannelType.GENZEON_FAX == 2
        assert ChannelType.ESMD == 3
    
    def test_channel_type_int_conversion(self):
        """Test ChannelType can be converted to int"""
        assert int(ChannelType.GENZEON_PORTAL) == 1
        assert int(ChannelType.GENZEON_FAX) == 2
        assert int(ChannelType.ESMD) == 3


class TestSendServiceOpsDBModel:
    """Test SendServiceOpsDB model with channel_type_id"""
    
    def test_model_has_channel_type_id_column(self):
        """Test SendServiceOpsDB has channel_type_id column"""
        assert hasattr(SendServiceOpsDB, 'channel_type_id')
    
    def test_channel_type_id_is_nullable(self):
        """Test channel_type_id is nullable for backward compatibility"""
        # Create instance without channel_type_id
        instance = SendServiceOpsDB(
            message_id=1,
            decision_tracking_id="test-uuid",
            payload={}
        )
        assert instance.channel_type_id is None
    
    def test_channel_type_id_can_be_set(self):
        """Test channel_type_id can be set"""
        instance = SendServiceOpsDB(
            message_id=1,
            decision_tracking_id="test-uuid",
            payload={},
            channel_type_id=ChannelType.GENZEON_PORTAL
        )
        assert instance.channel_type_id == ChannelType.GENZEON_PORTAL


class TestIntegrationInboxServiceChannelType:
    """Test IntegrationInboxService with channel_type_id support"""
    
    @pytest.fixture
    def inbox_service(self):
        """Create IntegrationInboxService instance"""
        return IntegrationInboxService()
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = MagicMock()
        return session
    
    @patch('app.services.integration_inbox.SessionLocal')
    def test_poll_new_messages_includes_channel_type_id(self, mock_session_local, inbox_service, mock_db_session):
        """Test poll_new_messages includes channel_type_id in query and results"""
        # Mock watermark
        mock_db_session.execute.return_value.fetchone.return_value = (
            datetime(2026, 1, 1),
            0
        )
        
        # Mock poll query result with channel_type_id
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (270, "04eb1038-f6cf-4359-81a0-cee8468fa3bb", {"documents": []}, datetime(2026, 1, 6), 3),  # ESMD
            (271, "e7b8c1e2-1234-4cde-9abc-1234567890ab", {"documents": []}, datetime(2026, 1, 6), 2),  # Fax
            (272, "b1c2d3e4-5678-4abc-9def-234567890abc", {"documents": []}, datetime(2026, 1, 6), 1),  # Portal
        ]
        mock_db_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_db_session
        
        messages = inbox_service.poll_new_messages(batch_size=10)
        
        # Verify channel_type_id is included in results
        assert len(messages) == 3
        assert messages[0]['channel_type_id'] == 3  # ESMD
        assert messages[1]['channel_type_id'] == 2  # Fax
        assert messages[2]['channel_type_id'] == 1  # Portal
        
        # Verify query includes channel_type_id in SELECT
        call_args = mock_db_session.execute.call_args
        assert call_args is not None
        query_text = str(call_args[0][0])
        assert 'channel_type_id' in query_text
    
    @patch('app.services.integration_inbox.SessionLocal')
    def test_poll_new_messages_handles_null_channel_type_id(self, mock_session_local, inbox_service, mock_db_session):
        """Test poll_new_messages handles NULL channel_type_id (backward compatibility)"""
        # Mock watermark
        mock_db_session.execute.return_value.fetchone.return_value = (
            datetime(2026, 1, 1),
            0
        )
        
        # Mock poll query result with NULL channel_type_id
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (100, "old-uuid", {"documents": []}, datetime(2026, 1, 1), None),  # NULL channel_type_id
        ]
        mock_db_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_db_session
        
        messages = inbox_service.poll_new_messages(batch_size=10)
        
        # Verify NULL channel_type_id is handled
        assert len(messages) == 1
        assert messages[0]['channel_type_id'] is None
    
    @patch('app.services.integration_inbox.SessionLocal')
    def test_insert_into_inbox_with_channel_type_id(self, mock_session_local, inbox_service, mock_db_session):
        """Test insert_into_inbox stores channel_type_id"""
        # Mock successful insert
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (123,)  # inbox_id
        mock_db_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_db_session
        
        inbox_id = inbox_service.insert_into_inbox(
            message_id=270,
            decision_tracking_id="04eb1038-f6cf-4359-81a0-cee8468fa3bb",
            message_type="ingest_file_package",
            source_created_at=datetime(2026, 1, 6),
            channel_type_id=ChannelType.ESMD
        )
        
        assert inbox_id == 123
        
        # Verify INSERT includes channel_type_id
        call_args = mock_db_session.execute.call_args
        assert call_args is not None
        query_text = str(call_args[0][0])
        assert 'channel_type_id' in query_text
        
        # Verify channel_type_id parameter is passed
        params = call_args[0][1]
        assert params['channel_type_id'] == ChannelType.ESMD
    
    @patch('app.services.integration_inbox.SessionLocal')
    def test_insert_into_inbox_without_channel_type_id(self, mock_session_local, inbox_service, mock_db_session):
        """Test insert_into_inbox works without channel_type_id (backward compatibility)"""
        # Mock successful insert
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (124,)
        mock_db_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_db_session
        
        inbox_id = inbox_service.insert_into_inbox(
            message_id=100,
            decision_tracking_id="old-uuid",
            message_type="ingest_file_package",
            source_created_at=datetime(2026, 1, 1)
            # channel_type_id not provided (defaults to None)
        )
        
        assert inbox_id == 124
        
        # Verify NULL channel_type_id is passed
        call_args = mock_db_session.execute.call_args
        params = call_args[0][1]
        assert params['channel_type_id'] is None
    
    @patch('app.services.integration_inbox.SessionLocal')
    def test_claim_job_returns_channel_type_id(self, mock_session_local, inbox_service, mock_db_session):
        """Test claim_job returns channel_type_id in result"""
        # Mock successful claim
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            123,  # inbox_id
            270,  # message_id
            "04eb1038-f6cf-4359-81a0-cee8468fa3bb",  # decision_tracking_id
            "ingest_file_package",  # message_type
            datetime(2026, 1, 6),  # source_created_at
            "PROCESSING",  # status
            1,  # attempt_count
            "worker-1",  # locked_by
            datetime(2026, 1, 6),  # locked_at
            3  # channel_type_id (ESMD)
        )
        mock_db_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_db_session
        
        job = inbox_service.claim_job(worker_id="worker-1")
        
        assert job is not None
        assert job['inbox_id'] == 123
        assert job['channel_type_id'] == 3  # ESMD
        
        # Verify query includes channel_type_id in SELECT
        call_args = mock_db_session.execute.call_args
        query_text = str(call_args[0][0])
        assert 'channel_type_id' in query_text
    
    @patch('app.services.integration_inbox.SessionLocal')
    def test_claim_job_handles_null_channel_type_id(self, mock_session_local, inbox_service, mock_db_session):
        """Test claim_job handles NULL channel_type_id"""
        # Mock successful claim with NULL channel_type_id
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (
            125,  # inbox_id
            100,  # message_id
            "old-uuid",  # decision_tracking_id
            "ingest_file_package",  # message_type
            datetime(2026, 1, 1),  # source_created_at
            "PROCESSING",  # status
            1,  # attempt_count
            "worker-1",  # locked_by
            datetime(2026, 1, 1),  # locked_at
            None  # channel_type_id (NULL)
        )
        mock_db_session.execute.return_value = mock_result
        mock_session_local.return_value = mock_db_session
        
        job = inbox_service.claim_job(worker_id="worker-1")
        
        assert job is not None
        assert job['channel_type_id'] is None

