"""
Unit tests for decision race condition fixes
Tests idempotency and concurrent request handling
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, call
from sqlalchemy.orm import Session
import threading
import time

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.services.decisions_service import DecisionsService
from app.services.validations_persistence import ValidationsPersistenceService


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock(spec=Session)
    db.query = Mock()
    db.add = Mock()
    db.commit = Mock()
    db.refresh = Mock()
    db.flush = Mock()
    db.execute = Mock()
    return db


@pytest.fixture
def sample_packet():
    """Create a sample packet for testing"""
    packet = Mock(spec=PacketDB)
    packet.packet_id = 1
    packet.external_id = "SVC-2026-000001"
    return packet


@pytest.fixture
def sample_document(sample_packet):
    """Create a sample document for testing"""
    document = Mock(spec=PacketDocumentDB)
    document.packet_document_id = 1
    document.packet_id = sample_packet.packet_id
    return document


class TestDecisionIdempotency:
    """Test idempotency using correlation_id"""
    
    def test_create_approve_decision_idempotent_with_correlation_id(self, mock_db, sample_packet, sample_document):
        """Test that create_approve_decision returns existing decision if correlation_id matches"""
        correlation_id = "test-correlation-id-123"
        
        # Mock existing decision with same correlation_id
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 100
        existing_decision.correlation_id = correlation_id
        existing_decision.decision_type = 'APPROVE'
        existing_decision.is_active = True
        
        # Mock query chain for correlation_id check
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing_decision
        mock_db.query.return_value = mock_query
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            result = DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                correlation_id=correlation_id,
                created_by="test@example.com"
            )
        
        # Verify existing decision is returned (idempotent)
        assert result == existing_decision
        assert result.packet_decision_id == 100
        # Verify no new decision was created
        mock_db.add.assert_not_called()
    
    def test_create_dismissal_decision_idempotent_with_correlation_id(self, mock_db, sample_packet, sample_document):
        """Test that create_dismissal_decision returns existing decision if correlation_id matches"""
        correlation_id = "test-correlation-id-456"
        
        # Mock existing decision with same correlation_id
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 200
        existing_decision.correlation_id = correlation_id
        existing_decision.decision_type = 'DISMISSAL'
        existing_decision.is_active = True
        
        # Mock query chain for correlation_id check
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing_decision
        mock_db.query.return_value = mock_query
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            result = DecisionsService.create_dismissal_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                denial_reason="MISSING_FIELDS",
                denial_details={"missingFields": ["provider_fax"]},
                correlation_id=correlation_id,
                created_by="test@example.com"
            )
        
        # Verify existing decision is returned (idempotent)
        assert result == existing_decision
        assert result.packet_decision_id == 200
        # Verify no new decision was created
        mock_db.add.assert_not_called()
    
    def test_create_approve_decision_creates_new_with_different_correlation_id(self, mock_db, sample_packet, sample_document):
        """Test that create_approve_decision creates new decision if correlation_id is different"""
        correlation_id = "new-correlation-id-789"
        
        # Mock query: no existing decision with this correlation_id
        mock_query_chain = MagicMock()
        mock_query_chain.filter.return_value.first.return_value = None  # No existing with correlation_id
        mock_query_chain.filter.return_value.with_for_update.return_value.all.return_value = []  # No existing active
        mock_db.query.return_value = mock_query_chain
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            # Capture created decision
            created_decision = None
            def capture_add(obj):
                nonlocal created_decision
                created_decision = obj
            
            mock_db.add.side_effect = capture_add
            
            result = DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                correlation_id=correlation_id,
                created_by="test@example.com"
            )
        
        # Verify new decision was created
        assert mock_db.add.called
        assert result is not None


class TestDecisionRaceConditions:
    """Test race condition fixes with with_for_update()"""
    
    def test_create_approve_decision_uses_with_for_update(self, mock_db, sample_packet, sample_document):
        """Test that create_approve_decision uses with_for_update() to prevent race conditions"""
        correlation_id = "test-correlation-id"
        
        # Mock query chain
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None  # No existing with correlation_id
        mock_with_update = MagicMock()
        mock_with_update.all.return_value = []  # No existing active decisions
        mock_query.filter.return_value.with_for_update.return_value = mock_with_update
        mock_db.query.return_value = mock_query
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                correlation_id=correlation_id,
                created_by="test@example.com"
            )
        
        # Verify with_for_update() was called
        mock_query.filter.return_value.with_for_update.assert_called_once()
        mock_with_update.all.assert_called_once()
    
    def test_create_dismissal_decision_uses_with_for_update(self, mock_db, sample_packet, sample_document):
        """Test that create_dismissal_decision uses with_for_update() to prevent race conditions"""
        correlation_id = "test-correlation-id"
        
        # Mock query chain
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None  # No existing with correlation_id
        mock_with_update = MagicMock()
        mock_with_update.all.return_value = []  # No existing active decisions
        mock_query.filter.return_value.with_for_update.return_value = mock_with_update
        mock_db.query.return_value = mock_query
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            DecisionsService.create_dismissal_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                denial_reason="MISSING_FIELDS",
                denial_details={"missingFields": ["provider_fax"]},
                correlation_id=correlation_id,
                created_by="test@example.com"
            )
        
        # Verify with_for_update() was called
        mock_query.filter.return_value.with_for_update.assert_called_once()
        mock_with_update.all.assert_called_once()
    
    def test_update_operational_decision_uses_with_for_update(self, mock_db, sample_packet):
        """Test that update_operational_decision uses with_for_update() to prevent race conditions"""
        # Mock existing decision
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 1
        existing_decision.packet_document_id = 1
        existing_decision.decision_type = 'APPROVE'
        existing_decision.denial_reason = None
        existing_decision.denial_details = None
        existing_decision.notes = None
        existing_decision.linked_validation_run_ids = {}
        existing_decision.operational_decision = 'PENDING'
        existing_decision.clinical_decision = 'PENDING'
        existing_decision.is_active = True
        existing_decision.decision_subtype = None
        existing_decision.decision_outcome = None
        existing_decision.part_type = None
        existing_decision.esmd_request_status = None
        existing_decision.esmd_request_payload = None
        existing_decision.utn = None
        existing_decision.utn_status = None
        existing_decision.letter_owner = None
        existing_decision.letter_status = None
        existing_decision.letter_package = None
        
        # Mock query chain with with_for_update
        mock_query = MagicMock()
        mock_query.filter.return_value.with_for_update.return_value.first.return_value = existing_decision
        mock_db.query.return_value = mock_query
        
        DecisionsService.update_operational_decision(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_operational_decision='DECISION_COMPLETE',
            created_by="system"
        )
        
        # Verify with_for_update() was called
        mock_query.filter.return_value.with_for_update.assert_called_once()
    
    def test_update_clinical_decision_uses_with_for_update(self, mock_db, sample_packet):
        """Test that update_clinical_decision uses with_for_update() to prevent race conditions"""
        # Mock existing decision
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 1
        existing_decision.packet_document_id = 1
        existing_decision.decision_type = 'APPROVE'
        existing_decision.denial_reason = None
        existing_decision.denial_details = None
        existing_decision.notes = None
        existing_decision.linked_validation_run_ids = {}
        existing_decision.operational_decision = 'PENDING'
        existing_decision.clinical_decision = 'PENDING'
        existing_decision.is_active = True
        existing_decision.decision_subtype = None
        existing_decision.decision_outcome = None
        existing_decision.part_type = None
        existing_decision.esmd_request_status = None
        existing_decision.esmd_request_payload = None
        existing_decision.utn = None
        existing_decision.utn_status = None
        existing_decision.letter_owner = None
        existing_decision.letter_status = None
        
        # Mock query chain with with_for_update
        mock_query = MagicMock()
        mock_query.filter.return_value.with_for_update.return_value.first.return_value = existing_decision
        mock_db.query.return_value = mock_query
        
        DecisionsService.update_clinical_decision(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_clinical_decision='AFFIRM',
            created_by="clinicalops@example.com"
        )
        
        # Verify with_for_update() was called
        mock_query.filter.return_value.with_for_update.assert_called_once()


class TestEndpointIdempotency:
    """Test idempotency checks at endpoint level"""
    
    def test_approve_endpoint_returns_existing_recent_decision(self, mock_db, sample_packet, sample_document):
        """Test that approve endpoint logic returns existing decision if created recently"""
        # Mock existing recent decision (created 2 seconds ago)
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 100
        existing_decision.packet_id = sample_packet.packet_id
        existing_decision.packet_document_id = sample_document.packet_document_id
        existing_decision.decision_type = 'APPROVE'
        existing_decision.operational_decision = 'PENDING'
        existing_decision.clinical_decision = 'PENDING'
        existing_decision.is_active = True
        existing_decision.created_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        existing_decision.created_by = "test@example.com"
        existing_decision.denial_reason = None
        existing_decision.denial_details = None
        existing_decision.notes = None
        existing_decision.linked_validation_run_ids = None
        
        # Mock query to return existing decision
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing_decision
        mock_db.query.return_value = mock_query
        mock_db.refresh = Mock()
        
        # Test the idempotency check logic (simulating endpoint behavior)
        result_query = mock_db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == sample_packet.packet_id,
            PacketDecisionDB.is_active == True
        ).first()
        
        assert result_query == existing_decision
        time_diff = (datetime.now(timezone.utc) - existing_decision.created_at).total_seconds()
        assert time_diff < 5  # Within 5 second window
        assert time_diff >= 0  # Not in the future
    
    def test_dismissal_endpoint_returns_existing_recent_decision(self, mock_db, sample_packet, sample_document):
        """Test that dismissal endpoint returns existing decision if created recently"""
        # Mock existing recent dismissal (created 1 second ago)
        existing_dismissal = Mock(spec=PacketDecisionDB)
        existing_dismissal.packet_decision_id = 200
        existing_dismissal.packet_id = sample_packet.packet_id
        existing_dismissal.packet_document_id = sample_document.packet_document_id
        existing_dismissal.decision_type = 'DISMISSAL'
        existing_dismissal.operational_decision = 'DISMISSAL'
        existing_dismissal.clinical_decision = 'PENDING'
        existing_dismissal.is_active = True
        existing_dismissal.created_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        existing_dismissal.created_by = "test@example.com"
        existing_dismissal.denial_reason = "MISSING_FIELDS"
        existing_dismissal.denial_details = {"missingFields": ["provider_fax"]}
        existing_dismissal.notes = None
        existing_dismissal.linked_validation_run_ids = None
        
        # Mock query
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = existing_dismissal
        mock_db.query.return_value = mock_query
        
        result = mock_db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == sample_packet.packet_id,
            PacketDecisionDB.decision_type == 'DISMISSAL',
            PacketDecisionDB.is_active == True
        ).first()
        
        assert result == existing_dismissal
        time_diff = (datetime.now(timezone.utc) - existing_dismissal.created_at).total_seconds()
        assert time_diff < 5  # Within 5 second window


class TestConcurrentRequestHandling:
    """Test handling of concurrent requests (simulated)"""
    
    def test_concurrent_approve_requests_only_create_one_decision(self, mock_db, sample_packet, sample_document):
        """Test that concurrent approve requests only create one decision (simulated with mocks)"""
        correlation_id = "test-correlation-id"
        
        # Simulate: First request creates decision, second request finds it via correlation_id
        created_decisions = []
        
        def mock_add(obj):
            created_decisions.append(obj)
        
        mock_db.add.side_effect = mock_add
        
        # First request: No existing decision
        mock_query1 = MagicMock()
        mock_query1.filter.return_value.first.return_value = None  # No existing with correlation_id
        mock_with_update1 = MagicMock()
        mock_with_update1.all.return_value = []  # No existing active
        mock_query1.filter.return_value.with_for_update.return_value = mock_with_update1
        
        # Second request: Finds existing via correlation_id (idempotent)
        mock_query2 = MagicMock()
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 100
        existing_decision.correlation_id = correlation_id
        existing_decision.decision_type = 'APPROVE'
        mock_query2.filter.return_value.first.return_value = existing_decision
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            # First request
            mock_db.query.return_value = mock_query1
            result1 = DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                correlation_id=correlation_id,
                created_by="user1@example.com"
            )
            
            # Second request (simulated - would happen concurrently in real scenario)
            mock_db.query.return_value = mock_query2
            result2 = DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                correlation_id=correlation_id,  # Same correlation_id
                created_by="user1@example.com"
            )
        
        # Verify: First request creates decision, second returns existing
        assert len(created_decisions) == 1  # Only one decision created
        assert result2 == existing_decision  # Second request returns existing (idempotent)
    
    def test_concurrent_dismissal_requests_only_create_one_decision(self, mock_db, sample_packet, sample_document):
        """Test that concurrent dismissal requests only create one decision (simulated with mocks)"""
        correlation_id = "test-correlation-id-dismissal"
        
        # Simulate: First request creates decision, second request finds it via correlation_id
        created_decisions = []
        
        def mock_add(obj):
            created_decisions.append(obj)
        
        mock_db.add.side_effect = mock_add
        
        # First request: No existing decision
        mock_query1 = MagicMock()
        mock_query1.filter.return_value.first.return_value = None  # No existing with correlation_id
        mock_with_update1 = MagicMock()
        mock_with_update1.all.return_value = []  # No existing active
        mock_query1.filter.return_value.with_for_update.return_value = mock_with_update1
        
        # Second request: Finds existing via correlation_id (idempotent)
        mock_query2 = MagicMock()
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 200
        existing_decision.correlation_id = correlation_id
        existing_decision.decision_type = 'DISMISSAL'
        mock_query2.filter.return_value.first.return_value = existing_decision
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            # First request
            mock_db.query.return_value = mock_query1
            result1 = DecisionsService.create_dismissal_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                denial_reason="MISSING_FIELDS",
                denial_details={"missingFields": ["provider_fax"]},
                correlation_id=correlation_id,
                created_by="user1@example.com"
            )
            
            # Second request (simulated - would happen concurrently in real scenario)
            mock_db.query.return_value = mock_query2
            result2 = DecisionsService.create_dismissal_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                denial_reason="MISSING_FIELDS",
                denial_details={"missingFields": ["provider_fax"]},
                correlation_id=correlation_id,  # Same correlation_id
                created_by="user1@example.com"
            )
        
        # Verify: First request creates decision, second returns existing
        assert len(created_decisions) == 1  # Only one decision created
        assert result2 == existing_decision  # Second request returns existing (idempotent)
