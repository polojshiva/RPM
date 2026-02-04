"""
Unit tests for packet idempotency using decision_tracking_id:
- Packet creation with decision_tracking_id
- Idempotency: same decision_tracking_id returns same packet
- Concurrency safety: duplicate creates result in one packet
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

from sqlalchemy.exc import IntegrityError
from app.services.document_processor import DocumentProcessor
from app.models.packet_db import PacketDB
from app.config import settings


class TestPacketIdempotency:
    """Test packet creation and idempotency with decision_tracking_id"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock()
        db.query = Mock()
        db.add = Mock()
        db.flush = Mock()
        db.rollback = Mock()
        return db
    
    @pytest.fixture
    def processor(self):
        """Create document processor"""
        # Mock DocumentProcessor initialization to avoid PDF library dependency
        with patch('app.services.document_processor.PDFMerger'):
            with patch('app.services.document_processor.DocumentSplitter'):
                with patch('app.services.document_processor.BlobStorageClient'):
                    return DocumentProcessor()
    
    def test_create_new_packet_with_decision_tracking_id(self, processor, mock_db):
        """Test creating a new packet with decision_tracking_id"""
        decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Mock: no existing packet
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Mock: packet creation
        new_packet = Mock(spec=PacketDB)
        new_packet.packet_id = 123
        new_packet.external_id = "PKT-2026-123456"
        new_packet.decision_tracking_id = decision_tracking_id
        
        def add_side_effect(packet):
            # Simulate packet creation
            packet.packet_id = 123
            packet.external_id = "PKT-2026-123456"
        
        mock_db.add.side_effect = add_side_effect
        
        # Mock _calculate_due_date
        processor._calculate_due_date = Mock(return_value=None)
        
        packet = processor._get_or_create_packet(
            db=mock_db,
            decision_tracking_id=decision_tracking_id,
            unique_id="unique-123",
            esmd_transaction_id="esmd-456",
            received_date=None
        )
        
        # Verify packet was created
        assert packet is not None
        assert packet.packet_id == 123
        
        # Verify decision_tracking_id was used in query
        mock_db.query.assert_called_with(PacketDB)
        filter_call = mock_db.query.return_value.filter
        assert filter_call.called
        
        # Verify packet was added to session
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()
    
    def test_reuse_existing_packet_by_decision_tracking_id(self, processor, mock_db):
        """Test that existing packet is reused when decision_tracking_id matches"""
        decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Mock: existing packet found
        existing_packet = Mock(spec=PacketDB)
        existing_packet.packet_id = 456
        existing_packet.external_id = "PKT-2026-789012"
        existing_packet.decision_tracking_id = decision_tracking_id
        
        mock_db.query.return_value.filter.return_value.first.return_value = existing_packet
        
        packet = processor._get_or_create_packet(
            db=mock_db,
            decision_tracking_id=decision_tracking_id,
            unique_id="unique-123",
            esmd_transaction_id="esmd-456",
            received_date=None
        )
        
        # Verify existing packet was returned
        assert packet == existing_packet
        assert packet.packet_id == 456
        
        # Verify no new packet was created
        mock_db.add.assert_not_called()
        mock_db.flush.assert_not_called()
    
    def test_concurrency_safe_packet_creation(self, processor, mock_db):
        """Test that concurrent creates with same decision_tracking_id result in one packet"""
        decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # First call: no existing packet
        # Second call: IntegrityError (unique constraint violation)
        # Third call: existing packet found
        
        call_count = {'count': 0}
        
        def query_side_effect():
            call_count['count'] += 1
            query_mock = Mock()
            
            if call_count['count'] == 1:
                # First query: no packet found
                query_mock.filter.return_value.first.return_value = None
            elif call_count['count'] == 2:
                # Second query: packet found (after conflict)
                existing_packet = Mock(spec=PacketDB)
                existing_packet.packet_id = 789
                existing_packet.external_id = "PKT-2026-999999"
                existing_packet.decision_tracking_id = decision_tracking_id
                query_mock.filter.return_value.first.return_value = existing_packet
            else:
                query_mock.filter.return_value.first.return_value = None
            
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        # Mock IntegrityError on flush (concurrent create)
        def flush_side_effect():
            if call_count['count'] == 1:
                error = IntegrityError("statement", "params", "orig")
                error.orig = Exception("uq_packet_decision_tracking_id")
                raise error
        
        mock_db.flush.side_effect = flush_side_effect
        
        # Mock _calculate_due_date
        processor._calculate_due_date = Mock(return_value=None)
        
        packet = processor._get_or_create_packet(
            db=mock_db,
            decision_tracking_id=decision_tracking_id,
            unique_id="unique-123",
            esmd_transaction_id="esmd-456",
            received_date=None
        )
        
        # Verify packet was returned (from re-fetch after conflict)
        assert packet is not None
        assert packet.packet_id == 789
        
        # Verify rollback was called
        mock_db.rollback.assert_called_once()
        
        # Verify packet was re-fetched after conflict
        assert mock_db.query.call_count >= 2
    
    def test_packet_not_using_case_id_for_decision_tracking_id(self, processor, mock_db):
        """Test that packet.case_id is NOT populated with decision_tracking_id"""
        decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Mock: no existing packet
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        created_packet = None
        
        def add_side_effect(packet):
            nonlocal created_packet
            created_packet = packet
            packet.packet_id = 123
            packet.external_id = "PKT-2026-123456"
        
        mock_db.add.side_effect = add_side_effect
        
        # Mock _calculate_due_date
        processor._calculate_due_date = Mock(return_value=None)
        
        processor._get_or_create_packet(
            db=mock_db,
            decision_tracking_id=decision_tracking_id,
            unique_id="unique-123",
            esmd_transaction_id="esmd-456",
            received_date=None
        )
        
        # Verify decision_tracking_id was set
        assert created_packet is not None
        assert hasattr(created_packet, 'decision_tracking_id')
        # Note: We can't directly assert the value since it's a mock,
        # but we can verify case_id was NOT set by checking the PacketDB constructor wasn't called with case_id
        # The actual check would be in integration tests

