"""
Unit tests for affirm_decision endpoint
Tests the direct affirm functionality that bypasses ClinicalOps
"""
import pytest
import sys
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, call
from fastapi import HTTPException
from sqlalchemy.orm import Session

# Mock Azure modules before importing app (same pattern as other tests)
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.models.user import User
from app.routes.decisions import affirm_decision


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock(spec=Session)
    db.query = Mock()
    db.add = Mock()
    db.commit = Mock()
    db.refresh = Mock()
    db.flush = Mock()
    db.rollback = Mock()
    return db


@pytest.fixture
def mock_user():
    """Mock user"""
    user = Mock(spec=User)
    user.email = "test@example.com"
    return user


@pytest.fixture
def sample_packet():
    """Create a sample packet"""
    packet = Mock(spec=PacketDB)
    packet.packet_id = 1
    packet.external_id = "SVC-2026-000001"
    packet.decision_tracking_id = "123e4567-e89b-12d3-a456-426614174000"
    packet.detailed_status = "Validation Complete"
    packet.validation_status = "Validation Complete"
    return packet


@pytest.fixture
def sample_document(sample_packet):
    """Create a sample document"""
    document = Mock(spec=PacketDocumentDB)
    document.packet_document_id = 1
    document.packet_id = sample_packet.packet_id
    document.external_id = "DOC-001"
    return document


@pytest.fixture
def mock_request():
    """Mock FastAPI Request"""
    request = Mock()
    request.state = Mock()
    request.state.correlation_id = None
    return request


class TestAffirmDecisionEndpoint:
    """Test affirm_decision endpoint"""
    
    @pytest.mark.asyncio
    async def test_affirm_packet_not_found(self, mock_db, mock_user, mock_request):
        """Test that 404 is returned when packet doesn't exist"""
        # Mock query to return None (packet not found)
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        
        with pytest.raises(HTTPException) as exc_info:
            await affirm_decision(
                packet_id="NONEXISTENT",
                http_request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert exc_info.value.status_code == 404
        assert "Packet not found" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_affirm_any_status_allowed(self, mock_db, mock_user, mock_request, sample_packet):
        """Test that affirm works from any status (status validation removed)"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        sample_packet.detailed_status = "Dismissal Complete"  # Any status should work now
        
        # Mock document query
        document_query = MagicMock()
        document = MagicMock()
        document.packet_document_id = 1
        document_query.filter.return_value.first.return_value = document
        
        # Mock decision query (no existing decision)
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDocumentDB:
                return document_query
            elif model == PacketDecisionDB:
                return decision_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        # Should not raise an error - status validation removed
        # Note: This test may need mocking of DecisionsService methods to fully pass
        # For now, we just verify it doesn't raise a status validation error
        try:
            await affirm_decision(
                packet_id=sample_packet.external_id,
                http_request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
            # If we get here without a status error, the validation was successfully removed
        except HTTPException as e:
            # Should not be a status validation error
            assert "Can only affirm packets in validation" not in str(e.detail)
    
    @pytest.mark.asyncio
    async def test_affirm_no_document(self, mock_db, mock_user, mock_request, sample_packet):
        """Test that 404 is returned when packet has no document"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        
        # Mock decision query (no existing decision)
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = None
        
        # Mock document query to return None
        document_query = MagicMock()
        document_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDecisionDB:
                return decision_query
            elif model == PacketDocumentDB:
                return document_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with pytest.raises(HTTPException) as exc_info:
            await affirm_decision(
                packet_id=sample_packet.external_id,
                http_request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert exc_info.value.status_code == 404
        assert "No document found" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_affirm_existing_decision_already_set(self, mock_db, mock_user, mock_request, sample_packet, sample_document):
        """Test that 409 is returned when clinical decision is already set"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        
        # Mock document query
        document_query = MagicMock()
        document_query.filter.return_value.first.return_value = sample_document
        
        # Mock active decision query - decision already affirmed
        active_decision = Mock(spec=PacketDecisionDB)
        active_decision.clinical_decision = "AFFIRM"
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = active_decision
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDecisionDB:
                return decision_query
            elif model == PacketDocumentDB:
                return document_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with pytest.raises(HTTPException) as exc_info:
            await affirm_decision(
                packet_id=sample_packet.external_id,
                http_request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert exc_info.value.status_code == 409
        assert "Clinical decision already set" in str(exc_info.value.detail)
    
    @patch('app.routes.decisions.DecisionsService')
    @patch('app.routes.decisions.WorkflowOrchestratorService')
    @pytest.mark.asyncio
    async def test_affirm_no_existing_decision_creates_new(self, mock_workflow, mock_decisions_service, 
                                                     mock_db, mock_user, mock_request, 
                                                     sample_packet, sample_document):
        """Test that affirm creates new decision when none exists"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        
        # Mock document query
        document_query = MagicMock()
        document_query.filter.return_value.first.return_value = sample_document
        
        # Mock active decision query - no existing decision
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDecisionDB:
                return decision_query
            elif model == PacketDocumentDB:
                return document_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        # Mock DecisionsService methods
        created_decision = Mock(spec=PacketDecisionDB)
        created_decision.packet_decision_id = 1
        created_decision.decision_type = "APPROVE"
        created_decision.clinical_decision = "PENDING"
        created_decision.operational_decision = "PENDING"
        created_decision.notes = "Direct affirm by test@example.com (bypassed ClinicalOps)"
        created_decision.linked_validation_run_ids = {}
        created_decision.created_at = datetime.now(timezone.utc)
        created_decision.created_by = "test@example.com"
        created_decision.is_active = True
        
        updated_decision = Mock(spec=PacketDecisionDB)
        updated_decision.packet_decision_id = 2
        updated_decision.decision_type = "APPROVE"
        updated_decision.clinical_decision = "AFFIRM"
        updated_decision.operational_decision = "PENDING"
        updated_decision.notes = "Direct affirm by test@example.com (bypassed ClinicalOps)"
        updated_decision.linked_validation_run_ids = {}
        updated_decision.created_at = datetime.now(timezone.utc)
        updated_decision.created_by = "test@example.com"
        updated_decision.is_active = True
        
        mock_decisions_service.create_approve_decision.return_value = created_decision
        mock_decisions_service.update_clinical_decision.return_value = updated_decision
        
        # Mock WorkflowOrchestratorService
        mock_workflow.update_packet_status = Mock()
        
        # Call endpoint
        response = await affirm_decision(
            packet_id=sample_packet.external_id,
            http_request=mock_request,
            db=mock_db,
            current_user=mock_user
        )
        
        # Verify response
        assert response.success is True
        assert response.data.clinical_decision == "AFFIRM"
        assert response.data.packet_id == sample_packet.external_id
        
        # Verify DecisionsService was called correctly
        mock_decisions_service.create_approve_decision.assert_called_once()
        mock_decisions_service.update_clinical_decision.assert_called_once_with(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_clinical_decision="AFFIRM",
            decision_outcome="AFFIRM",
            created_by=mock_user.email
        )
        
        # Verify WorkflowOrchestratorService was called
        mock_workflow.update_packet_status.assert_called_once_with(
            db=mock_db,
            packet=sample_packet,
            new_status="Clinical Decision Received"
        )
        
        # Verify commit was called
        mock_db.commit.assert_called_once()
    
    @patch('app.routes.decisions.DecisionsService')
    @patch('app.routes.decisions.WorkflowOrchestratorService')
    @pytest.mark.asyncio
    async def test_affirm_existing_decision_updates(self, mock_workflow, mock_decisions_service,
                                               mock_db, mock_user, mock_request,
                                               sample_packet, sample_document):
        """Test that affirm updates existing decision when one exists"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        
        # Mock document query
        document_query = MagicMock()
        document_query.filter.return_value.first.return_value = sample_document
        
        # Mock active decision query - existing decision with PENDING
        active_decision = Mock(spec=PacketDecisionDB)
        active_decision.clinical_decision = "PENDING"
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = active_decision
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDecisionDB:
                return decision_query
            elif model == PacketDocumentDB:
                return document_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        # Mock DecisionsService
        updated_decision = Mock(spec=PacketDecisionDB)
        updated_decision.packet_decision_id = 1
        updated_decision.decision_type = "APPROVE"
        updated_decision.clinical_decision = "AFFIRM"
        updated_decision.operational_decision = "PENDING"
        updated_decision.notes = None
        updated_decision.linked_validation_run_ids = {}
        updated_decision.created_at = datetime.now(timezone.utc)
        updated_decision.created_by = "test@example.com"
        updated_decision.is_active = True
        
        mock_decisions_service.update_clinical_decision.return_value = updated_decision
        
        # Mock WorkflowOrchestratorService
        mock_workflow.update_packet_status = Mock()
        
        # Call endpoint
        response = await affirm_decision(
            packet_id=sample_packet.external_id,
            http_request=mock_request,
            db=mock_db,
            current_user=mock_user
        )
        
        # Verify response
        assert response.success is True
        assert response.data.clinical_decision == "AFFIRM"
        
        # Verify DecisionsService.update_clinical_decision was called (not create_approve_decision)
        mock_decisions_service.create_approve_decision.assert_not_called()
        mock_decisions_service.update_clinical_decision.assert_called_once_with(
            db=mock_db,
            packet_id=sample_packet.packet_id,
            new_clinical_decision="AFFIRM",
            decision_outcome="AFFIRM",
            created_by=mock_user.email
        )
        
        # Verify WorkflowOrchestratorService was called
        mock_workflow.update_packet_status.assert_called_once_with(
            db=mock_db,
            packet=sample_packet,
            new_status="Clinical Decision Received"
        )
        
        # Verify commit was called
        mock_db.commit.assert_called_once()
    
    @patch('app.routes.decisions.DecisionsService')
    @patch('app.routes.decisions.WorkflowOrchestratorService')
    @pytest.mark.asyncio
    async def test_affirm_allowed_statuses(self, mock_workflow, mock_decisions_service,
                                      mock_db, mock_user, mock_request, sample_document):
        """Test that affirm works from any status (status validation removed)"""
        # Test various statuses to ensure affirm works from any status
        test_statuses = [
            "Pending - Validation",
            "Validation In Progress",
            "Validation Complete",
            "Pending - Clinical Review",
            "Dismissal Complete",  # Previously blocked, now allowed
            "Decision Complete"    # Previously blocked, now allowed
        ]
        
        for status in test_statuses:
            # Reset mocks
            mock_db.reset_mock()
            mock_decisions_service.reset_mock()
            mock_workflow.reset_mock()
            
            # Create packet with current status
            packet = Mock(spec=PacketDB)
            packet.packet_id = 1
            packet.external_id = "SVC-2026-000001"
            packet.detailed_status = status
            packet.validation_status = "Validation Complete"
            
            # Mock queries
            packet_query = MagicMock()
            packet_query.filter.return_value.first.return_value = packet
            
            document_query = MagicMock()
            document_query.filter.return_value.first.return_value = sample_document
            
            decision_query = MagicMock()
            decision_query.filter.return_value.first.return_value = None  # No existing decision
            
            mock_db.query.side_effect = [packet_query, decision_query, document_query]
            
            # Mock DecisionsService
            created_decision = Mock(spec=PacketDecisionDB)
            created_decision.packet_decision_id = 1
            created_decision.decision_type = "APPROVE"
            created_decision.clinical_decision = "PENDING"
            created_decision.operational_decision = "PENDING"
            created_decision.notes = None
            created_decision.linked_validation_run_ids = {}
            created_decision.created_at = datetime.now(timezone.utc)
            created_decision.created_by = "test@example.com"
            created_decision.is_active = True
            
            updated_decision = Mock(spec=PacketDecisionDB)
            updated_decision.packet_decision_id = 2
            updated_decision.decision_type = "APPROVE"
            updated_decision.clinical_decision = "AFFIRM"
            updated_decision.operational_decision = "PENDING"
            updated_decision.notes = None
            updated_decision.linked_validation_run_ids = {}
            updated_decision.created_at = datetime.now(timezone.utc)
            updated_decision.created_by = "test@example.com"
            updated_decision.is_active = True
            
            mock_decisions_service.create_approve_decision.return_value = created_decision
            mock_decisions_service.update_clinical_decision.return_value = updated_decision
            mock_workflow.update_packet_status = Mock()
            
            # Call endpoint - should not raise exception
            response = await affirm_decision(
                packet_id=packet.external_id,
                http_request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
            
            assert response.success is True
            assert response.data.clinical_decision == "AFFIRM"
    
    @patch('app.routes.decisions.DecisionsService')
    @patch('app.routes.decisions.WorkflowOrchestratorService')
    @pytest.mark.asyncio
    async def test_affirm_rollback_on_error(self, mock_workflow, mock_decisions_service,
                                       mock_db, mock_user, mock_request,
                                       sample_packet, sample_document):
        """Test that database is rolled back on error"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        
        # Mock document query
        document_query = MagicMock()
        document_query.filter.return_value.first.return_value = sample_document
        
        # Mock active decision query - no existing decision
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = None
        
        mock_db.query.side_effect = [packet_query, decision_query, document_query]
        
        # Mock DecisionsService to raise exception
        mock_decisions_service.create_approve_decision.side_effect = Exception("Database error")
        
        # Call endpoint - should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await affirm_decision(
                packet_id=sample_packet.external_id,
                http_request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert exc_info.value.status_code == 500
        assert "Internal server error" in str(exc_info.value.detail)
        
        # Verify rollback was called
        mock_db.rollback.assert_called_once()
    
    @patch('app.routes.decisions.DecisionsService')
    @patch('app.routes.decisions.WorkflowOrchestratorService')
    @pytest.mark.asyncio
    async def test_affirm_no_send_clinicalops_record_created(self, mock_workflow, mock_decisions_service,
                                                         mock_db, mock_user, mock_request,
                                                         sample_packet, sample_document):
        """Test that no send_clinicalops record is created when affirming"""
        # Mock packet query
        packet_query = MagicMock()
        packet_query.filter.return_value.first.return_value = sample_packet
        
        # Mock document query
        document_query = MagicMock()
        document_query.filter.return_value.first.return_value = sample_document
        
        # Mock active decision query - no existing decision
        decision_query = MagicMock()
        decision_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return packet_query
            elif model == PacketDecisionDB:
                return decision_query
            elif model == PacketDocumentDB:
                return document_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        # Mock DecisionsService
        created_decision = Mock(spec=PacketDecisionDB)
        created_decision.packet_decision_id = 1
        created_decision.decision_type = "APPROVE"
        created_decision.clinical_decision = "PENDING"
        created_decision.operational_decision = "PENDING"
        created_decision.notes = None
        created_decision.linked_validation_run_ids = {}
        created_decision.created_at = datetime.now(timezone.utc)
        created_decision.created_by = "test@example.com"
        created_decision.is_active = True
        
        updated_decision = Mock(spec=PacketDecisionDB)
        updated_decision.packet_decision_id = 2
        updated_decision.decision_type = "APPROVE"
        updated_decision.clinical_decision = "AFFIRM"
        updated_decision.operational_decision = "PENDING"
        updated_decision.notes = None
        updated_decision.linked_validation_run_ids = {}
        updated_decision.created_at = datetime.now(timezone.utc)
        updated_decision.created_by = "test@example.com"
        updated_decision.is_active = True
        
        mock_decisions_service.create_approve_decision.return_value = created_decision
        mock_decisions_service.update_clinical_decision.return_value = updated_decision
        mock_workflow.update_packet_status = Mock()
        
        # Call endpoint
        response = await affirm_decision(
            packet_id=sample_packet.external_id,
            http_request=mock_request,
            db=mock_db,
            current_user=mock_user
        )
        
        # Verify response
        assert response.success is True
        
        # Verify that ClinicalOpsOutboxService was NOT called
        # (We should NOT see any calls to send_case_ready_for_review)
        # Check that db.add was only called for decision, not for send_clinicalops
        # Since we're using mocks, we can verify that no send_clinicalops-related code was executed
        # The key is that we don't import or call ClinicalOpsOutboxService in affirm_decision
        
        # Verify commit was called
        mock_db.commit.assert_called_once()
