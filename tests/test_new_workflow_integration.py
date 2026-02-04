"""
Integration tests for new workflow
Tests all three workflow paths: Decision Complete, UTN Fail, Dismissal Complete
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from unittest.mock import Mock, patch, AsyncMock

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.services.decisions_service import DecisionsService
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.services.utn_handlers import UtnSuccessHandler, UtnFailHandler
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor


@pytest.fixture
def mock_db():
    """Mock database session"""
    from unittest.mock import MagicMock
    db = MagicMock(spec=Session)
    db.query = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    db.flush = MagicMock()
    db.refresh = MagicMock()
    return db


@pytest.fixture
def sample_packet(mock_db) -> PacketDB:
    """Create a sample packet for testing"""
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


class TestDecisionCompleteWorkflow:
    """Test Decision Complete workflow (Happy Path)"""
    
    def test_approve_decision_workflow(self, mock_db, sample_packet, sample_document):
        """Test approve decision sets correct status and operational decision"""
        from unittest.mock import patch
        
        # Mock query to return empty list (no existing decisions)
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        # Mock ValidationsPersistenceService
        with patch('app.services.decisions_service.ValidationsPersistenceService') as mock_validations:
            mock_validations.get_last_validation_run_ids.return_value = {}
            
            # User clicks Approve
            decision = DecisionsService.create_approve_decision(
                db=mock_db,
                packet_id=sample_packet.packet_id,
                packet_document_id=sample_document.packet_document_id,
                created_by="user@example.com"
            )
        
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Pending - Clinical Review",
            validation_status="Validation Complete",
            release_lock=True
        )
        
        # Verify status
        assert sample_packet.detailed_status == "Pending - Clinical Review"
        assert sample_packet.validation_status == "Validation Complete"
        assert sample_packet.assigned_to is None
        
        # Verify operational decision stays PENDING
        assert decision.operational_decision == 'PENDING'
        assert decision.clinical_decision == 'PENDING'
    
    @pytest.mark.asyncio
    async def test_clinical_decision_received_workflow(self, mock_db, sample_packet, sample_document):
        """Test clinical decision received updates clinical_decision"""
        from unittest.mock import patch
        
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
        mock_query.filter.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        
        # Simulate ClinicalOps decision
        updated_decision = DecisionsService.update_clinical_decision(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_clinical_decision='AFFIRM',
            decision_subtype='STANDARD_PA',
            part_type='B',
            decision_outcome='AFFIRM',
            created_by="clinicalops@example.com"
        )
        
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Clinical Decision Received"
        )
        
        # Verify clinical decision updated
        assert updated_decision.clinical_decision == 'AFFIRM'
        assert updated_decision.operational_decision == 'PENDING'  # Still PENDING
        assert sample_packet.detailed_status == "Clinical Decision Received"
    
    @pytest.mark.asyncio
    async def test_utn_success_triggers_letter_generation(self, mock_db, sample_packet, sample_document):
        import asyncio
        """Test UTN_SUCCESS triggers letter generation and updates status"""
        from unittest.mock import patch
        
        # Mock decision with AFFIRM
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.packet_id = sample_packet.packet_id
        mock_decision.decision_outcome = 'AFFIRM'
        mock_decision.utn = None
        mock_decision.utn_status = None
        mock_decision.letter_status = None
        mock_decision.esmd_request_status = 'SENT'
        
        # Mock query to return decision
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_decision
        mock_db.query.return_value = mock_query
        
        # Mock UTN_SUCCESS message
        utn_message = {
            'message_id': 1,
            'decision_tracking_id': str(sample_packet.decision_tracking_id),
            'payload': {
                'unique_tracking_number': 'UTN123456',
                'esmd_transaction_id': 'ESMD123'
            }
        }
        
        # Mock letter generation
        with patch('app.services.utn_handlers.LetterGenerationService') as mock_letter_service:
            mock_service_instance = Mock()
            mock_service_instance.generate_letter.return_value = {
                'blob_url': 'https://blob.test/letter.pdf',
                'filename': 'letter.pdf',
                'file_size_bytes': 1024
            }
            mock_letter_service.return_value = mock_service_instance
            
            # Mock packet document query
            mock_db.query.return_value.filter.return_value.first.return_value = sample_document
            
            # Handle UTN_SUCCESS
            await UtnSuccessHandler.handle(mock_db, utn_message)
        
        # Verify UTN stored
        assert mock_decision.utn == 'UTN123456'
        assert mock_decision.utn_status == 'SUCCESS'
        
        # Verify status updated
        assert sample_packet.detailed_status in ["UTN Received", "Generate Decision Letter - Complete"]


class TestUTNFailWorkflow:
    """Test UTN Fail remediation workflow"""
    
    def test_utn_fail_loops_back_to_validation(self, mock_db, sample_packet, sample_document):
        """Test UTN_FAIL loops back to Validation status"""
        # Mock decision with AFFIRM
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.packet_id = sample_packet.packet_id
        mock_decision.decision_outcome = 'AFFIRM'
        mock_decision.utn_status = None
        mock_decision.requires_utn_fix = False
        mock_decision.esmd_request_status = 'SENT'
        mock_decision.part_type = None
        
        # Mock query to return decision and packet
        mock_query = MagicMock()
        mock_query.filter.return_value.first.side_effect = [sample_packet, mock_decision]
        mock_db.query.return_value = mock_query
        
        # Set status to "Pending - UTN"
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Pending - UTN"
        )
        
        # Mock UTN_FAIL message
        utn_fail_message = {
            'message_id': 1,
            'decision_tracking_id': str(sample_packet.decision_tracking_id),
            'payload': {
                'error_code': 'INVALID_MBI',
                'error_description': 'Invalid MBI format',
                'action_required': 'Please correct MBI and resubmit'
            }
        }
        
        # Handle UTN_FAIL
        UtnFailHandler.handle(mock_db, utn_fail_message)
        
        # Verify status looped back to Validation
        assert sample_packet.detailed_status == "Validation"
        assert sample_packet.validation_status == "Pending - Validation"
        
        # Verify UTN fail flags set
        assert mock_decision.utn_status == 'FAILED'
        assert mock_decision.requires_utn_fix == True


class TestDismissalWorkflow:
    """Test Dismissal Complete workflow"""
    
    def test_dismissal_decision_sets_operational_dismissal(self, mock_db, sample_packet, sample_document):
        """Test dismissal decision sets operational_decision to DISMISSAL"""
        from unittest.mock import patch
        
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
                created_by="user@example.com"
            )
        
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Dismissal",
            validation_status="Validation Complete",
            release_lock=True
        )
        
        # Verify operational decision is DISMISSAL
        assert decision.operational_decision == 'DISMISSAL'
        assert decision.clinical_decision == 'PENDING'  # Never sent to ClinicalOps
        assert sample_packet.detailed_status == "Dismissal"
    
    def test_dismissal_complete_updates_operational_decision(self, mock_db, sample_packet, sample_document):
        """Test dismissal complete updates operational_decision to DISMISSAL_COMPLETE"""
        # Mock initial dismissal decision
        initial_decision = Mock(spec=PacketDecisionDB)
        initial_decision.packet_decision_id = 1
        initial_decision.packet_id = sample_packet.packet_id
        initial_decision.packet_document_id = sample_document.packet_document_id
        initial_decision.operational_decision = 'DISMISSAL'
        initial_decision.clinical_decision = 'PENDING'
        initial_decision.is_active = True
        initial_decision.decision_type = 'DISMISSAL'
        initial_decision.denial_reason = "INVALID_MBI"
        initial_decision.denial_details = {"reason": "Invalid MBI format"}
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
        
        # Update to DISMISSAL_COMPLETE (simulating letter sent)
        updated_decision = DecisionsService.update_operational_decision(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_operational_decision='DISMISSAL_COMPLETE',
            created_by="system"
        )
        
        WorkflowOrchestratorService.update_packet_status(
            db=mock_db,
            packet=sample_packet,
            new_status="Dismissal Complete"
        )
        
        # Verify final state
        assert updated_decision.operational_decision == 'DISMISSAL_COMPLETE'
        assert updated_decision.clinical_decision == 'PENDING'
        assert sample_packet.detailed_status == "Dismissal Complete"

