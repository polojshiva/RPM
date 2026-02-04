"""
Unit tests for new workflow decision model
Tests DecisionsService with operational_decision and clinical_decision
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy.orm import Session

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.services.decisions_service import DecisionsService
from app.services.workflow_orchestrator import WorkflowOrchestratorService


@pytest.fixture
def mock_db():
    """Mock database session"""
    from unittest.mock import Mock
    db = Mock()
    db.query = Mock()
    db.add = Mock()
    db.commit = Mock()
    db.refresh = Mock()
    db.flush = Mock()
    return db


@pytest.fixture
def sample_packet(mock_db) -> PacketDB:
    """Create a sample packet for testing"""
    from unittest.mock import Mock
    packet = Mock(spec=PacketDB)
    packet.packet_id = 1
    packet.external_id = "SVC-2026-000001"
    packet.decision_tracking_id = "123e4567-e89b-12d3-a456-426614174000"
    packet.beneficiary_name = "John Doe"
    packet.beneficiary_mbi = "1AB2CD3EF45"
    packet.provider_name = "Test Provider"
    packet.provider_npi = "1234567890"
    packet.service_type = "Test Service"
    packet.received_date = datetime.now(timezone.utc)
    packet.due_date = datetime.now(timezone.utc)
    packet.detailed_status = "Pending - New"
    packet.validation_status = "Pending - Validation"
    packet.assigned_to = None
    packet.updated_at = datetime.now(timezone.utc)
    return packet


@pytest.fixture
def sample_document(mock_db, sample_packet) -> PacketDocumentDB:
    """Create a sample document for testing"""
    from unittest.mock import Mock
    document = Mock(spec=PacketDocumentDB)
    document.packet_document_id = 1
    document.packet_id = sample_packet.packet_id
    document.external_id = "DOC-001"
    document.blob_path = "test/blob/path"
    document.file_name = "test.pdf"
    document.file_size = 1024
    document.page_count = 1
    document.created_at = datetime.now(timezone.utc)
    return document


class TestDecisionsService:
    """Test DecisionsService with new workflow model"""
    
    def test_create_approve_decision_sets_operational_pending(self, mock_db, sample_packet, sample_document):
        """Test that approve decision sets operational_decision to PENDING"""
        # Mock query to return empty list (no existing decisions)
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        # Capture the decision object that gets created
        captured_decision = None
        
        def capture_add(obj):
            nonlocal captured_decision
            if hasattr(obj, 'operational_decision'):
                captured_decision = obj
        
        mock_db.add.side_effect = capture_add
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            decision = DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                created_by="test@example.com"
            )
        
        # Verify decision was created with correct fields
        assert decision.operational_decision == 'PENDING'
        assert decision.clinical_decision == 'PENDING'
        assert decision.is_active == True
        assert decision.decision_type == 'APPROVE'
    
    def test_create_dismissal_decision_sets_operational_dismissal(self, mock_db, sample_packet, sample_document):
        """Test that dismissal decision sets operational_decision to DISMISSAL"""
        # Mock query to return empty list (no existing decisions)
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            decision = DecisionsService.create_dismissal_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                denial_reason="INVALID_MBI",
                denial_details={"reason": "Invalid MBI format"},
                created_by="test@example.com"
            )
        
        # Verify decision was created with correct fields
        assert decision.operational_decision == 'DISMISSAL'
        assert decision.clinical_decision == 'PENDING'
        assert decision.is_active == True
        assert decision.decision_type == 'DISMISSAL'
    
    def test_update_operational_decision_creates_new_record(self, mock_db, sample_packet, sample_document):
        """Test that updating operational decision creates new record for audit trail"""
        # Mock initial decision
        initial_decision = Mock(spec=PacketDecisionDB)
        initial_decision.packet_decision_id = 1
        initial_decision.packet_id = sample_packet.packet_id
        initial_decision.packet_document_id = sample_document.packet_document_id
        initial_decision.operational_decision = 'PENDING'
        initial_decision.clinical_decision = 'PENDING'
        initial_decision.is_active = True
        initial_decision.decision_type = 'APPROVE'
        initial_decision.denial_reason = None
        initial_decision.denial_details = None
        initial_decision.notes = None
        initial_decision.linked_validation_run_ids = {}
        initial_decision.decision_subtype = None
        initial_decision.decision_outcome = None
        initial_decision.part_type = None
        initial_decision.esmd_request_status = None
        initial_decision.esmd_request_payload = None
        initial_decision.utn = None
        initial_decision.utn_status = None
        initial_decision.letter_owner = None
        initial_decision.letter_status = None
        initial_decision.letter_package = None
        
        # Mock query to return initial decision
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = initial_decision
        mock_db.query.return_value = mock_query
        
        updated_decision = DecisionsService.update_operational_decision(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_operational_decision='DECISION_COMPLETE',
            created_by="system"
        )
        
        # Verify old decision is deactivated
        assert initial_decision.is_active == False
        assert initial_decision.superseded_by == updated_decision.packet_decision_id
        
        # Verify new decision
        assert updated_decision.packet_decision_id != initial_decision.packet_decision_id
        assert updated_decision.operational_decision == 'DECISION_COMPLETE'
        assert updated_decision.is_active == True
        assert updated_decision.supersedes == initial_decision.packet_decision_id
    
    def test_update_clinical_decision_creates_new_record(self, mock_db, sample_packet, sample_document):
        """Test that updating clinical decision creates new record for audit trail"""
        # Mock initial decision
        initial_decision = Mock(spec=PacketDecisionDB)
        initial_decision.packet_decision_id = 1
        initial_decision.packet_id = sample_packet.packet_id
        initial_decision.packet_document_id = sample_document.packet_document_id
        initial_decision.operational_decision = 'PENDING'
        initial_decision.clinical_decision = 'PENDING'
        initial_decision.is_active = True
        initial_decision.decision_type = 'APPROVE'
        initial_decision.denial_reason = None
        initial_decision.denial_details = None
        initial_decision.notes = None
        initial_decision.linked_validation_run_ids = {}
        initial_decision.decision_subtype = None
        initial_decision.decision_outcome = None
        initial_decision.part_type = None
        initial_decision.esmd_request_status = None
        initial_decision.esmd_request_payload = None
        initial_decision.utn = None
        initial_decision.utn_status = None
        initial_decision.letter_owner = None
        initial_decision.letter_status = None
        
        # Mock query to return initial decision
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = initial_decision
        mock_db.query.return_value = mock_query
        
        updated_decision = DecisionsService.update_clinical_decision(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_clinical_decision='AFFIRM',
            decision_subtype='STANDARD_PA',
            part_type='B',
            decision_outcome='AFFIRM',
            created_by="clinicalops@example.com"
        )
        
        # Verify old decision is deactivated
        assert initial_decision.is_active == False
        assert initial_decision.superseded_by == updated_decision.packet_decision_id
        
        # Verify new decision
        assert updated_decision.packet_decision_id != initial_decision.packet_decision_id
        assert updated_decision.clinical_decision == 'AFFIRM'
        assert updated_decision.operational_decision == 'PENDING'  # Preserved
        assert updated_decision.is_active == True
        assert updated_decision.supersedes == initial_decision.packet_decision_id


class TestWorkflowOrchestratorService:
    """Test WorkflowOrchestratorService"""
    
    def test_update_packet_status(self, mock_db, sample_packet):
        """Test updating packet status"""
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Intake",
            validation_status="Pending - Validation",
            release_lock=False
        )
        
        assert sample_packet.detailed_status == "Intake"
        assert sample_packet.validation_status == "Pending - Validation"
    
    def test_update_packet_status_releases_lock(self, mock_db, sample_packet):
        """Test that update_packet_status can release lock"""
        sample_packet.assigned_to = "user@example.com"
        
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Pending - Clinical Review",
            release_lock=True
        )
        
        assert sample_packet.assigned_to is None
    
    def test_create_validation_record(self, mock_db, sample_packet, sample_document):
        """Test creating validation record"""
        # Mock query to return empty list (no existing validations)
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        validation = WorkflowOrchestratorService.create_validation_record(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            packet_document_id=sample_document.packet_document_id,
            validation_status="Validation Complete",
            validation_type="FINAL",
            is_passed=True,
            validated_by="user@example.com"
        )
        
        assert validation.validation_status == "Validation Complete"
        assert validation.validation_type == "FINAL"
        assert validation.is_passed == True
        assert validation.is_active == True
        assert validation.validated_by == "user@example.com"
    
    def test_get_active_decision(self, mock_db, sample_packet, sample_document):
        """Test getting active decision"""
        # Mock decision
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.is_active = True
        
        # Mock query to return decision
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_decision
        mock_db.query.return_value = mock_query
        
        active = WorkflowOrchestratorService.get_active_decision(mock_db, sample_packet.packet_id)
        
        assert active is not None
        assert active.packet_decision_id == mock_decision.packet_decision_id
        assert active.is_active == True
    
    def test_get_active_validation(self, mock_db, sample_packet, sample_document):
        """Test getting active validation"""
        # Mock validation
        mock_validation = Mock()
        mock_validation.packet_validation_id = 1
        mock_validation.is_active = True
        
        # Mock query to return validation
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_validation
        mock_db.query.return_value = mock_query
        
        active = WorkflowOrchestratorService.get_active_validation(mock_db, sample_packet.packet_id)
        
        assert active is not None
        assert active.packet_validation_id == mock_validation.packet_validation_id
        assert active.is_active == True

