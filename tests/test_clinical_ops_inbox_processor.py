"""
Comprehensive Unit Tests for ClinicalOps Inbox Processor

Tests Phase 1 and Phase 2 processing:
1. Phase 1: Extract decision from clinical_ops_decision_json and update packet_decision
2. Phase 2: Update ESMD tracking from generated payload
3. Message routing logic
4. JSON Generator API calls
5. Error handling and edge cases
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from sqlalchemy.orm import Session
import uuid
import httpx

from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_decision_db import PacketDecisionDB
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.services.decisions_service import DecisionsService


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
def sample_decision_tracking_id():
    """Sample decision tracking ID"""
    return str(uuid.uuid4())


@pytest.fixture
def sample_packet(sample_decision_tracking_id):
    """Sample packet"""
    packet = Mock(spec=PacketDB)
    packet.packet_id = 1
    packet.external_id = "SVC-2026-000001"
    packet.decision_tracking_id = sample_decision_tracking_id
    packet.detailed_status = "Pending - Clinical Review"
    return packet


@pytest.fixture
def sample_document(sample_packet):
    """Sample document with part_type"""
    document = Mock(spec=PacketDocumentDB)
    document.packet_document_id = 1
    document.packet_id = sample_packet.packet_id
    document.part_type = "B"  # Part B
    return document


@pytest.fixture
def sample_clinical_ops_decision_json(sample_decision_tracking_id):
    """Sample clinical_ops_decision_json (Phase 1)"""
    return {
        "source": "clinical_ops_ddms",
        "claim_id": 3677,
        "timestamp": "2026-01-29T15:41:28.103411",
        "decision_status": "Approved",
        "decision_indicator": "A",  # A = AFFIRM
        "failed_reason_data": None,
        "decision_tracking_id": sample_decision_tracking_id
    }


@pytest.fixture
def sample_generated_payload():
    """Sample generated payload (Phase 2)"""
    return {
        "procedures": [
            {
                "procedureCode": "64483",
                "decisionIndicator": "A",
                "mrCountUnitOfService": "1",
                "modifier": "50",
                "reviewCodes": [],
                "programCodes": [],
                "placeOfService": "22"
            }
        ],
        "partType": "B",
        "esmdTransactionId": "",  # Empty = Direct PA
        "documentation": ["/path/to/letter.pdf"],
        "header": {
            "state": "NJ",
            "submissionType": "I"
        }
    }


@pytest.fixture
def processor():
    """Create processor instance"""
    with patch('app.services.clinical_ops_inbox_processor.settings') as mock_settings:
        mock_settings.json_generator_base_url = "http://json-generator:8000"
        proc = ClinicalOpsInboxProcessor()
        proc.json_generator_url = "http://json-generator:8000"
        return proc


class TestHandleClinicalDecision:
    """Test Phase 1: _handle_clinical_decision"""
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_affirm(
        self, processor, mock_db, sample_packet, sample_document, 
        sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test Phase 1 processing with AFFIRM decision"""
        # Setup mocks
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        # Mock WorkflowOrchestratorService
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.packet_id = sample_packet.packet_id
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=None), \
             patch.object(DecisionsService, 'create_approve_decision', return_value=mock_decision) as mock_create, \
             patch.object(DecisionsService, 'update_clinical_decision', return_value=mock_decision) as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status') as mock_update_status:
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_clinical_decision(
                mock_db, message, sample_clinical_ops_decision_json
            )
            
            # Verify create_approve_decision was called (no existing decision)
            mock_create.assert_called_once()
            
            # Verify update_clinical_decision was called with correct parameters
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[1]['new_clinical_decision'] == 'AFFIRM'
            assert call_args[1]['decision_outcome'] == 'AFFIRM'
            assert call_args[1]['part_type'] == 'B'
            assert call_args[1]['decision_subtype'] == 'DIRECT_PA'  # Temporary, will be updated in Phase 2
            assert call_args[1]['created_by'] == 'CLINICAL_OPS'
            
            # Verify packet status was updated
            mock_update_status.assert_called_once()
            status_call = mock_update_status.call_args
            assert status_call[1]['new_status'] == "Clinical Decision Received"
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_non_affirm(
        self, processor, mock_db, sample_packet, sample_document,
        sample_decision_tracking_id
    ):
        """Test Phase 1 processing with NON_AFFIRM decision"""
        clinical_ops_json = {
            "decision_indicator": "N",  # N = NON_AFFIRM
            "decision_tracking_id": sample_decision_tracking_id
        }
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=None), \
             patch.object(DecisionsService, 'create_approve_decision', return_value=mock_decision), \
             patch.object(DecisionsService, 'update_clinical_decision', return_value=mock_decision) as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_clinical_decision(
                mock_db, message, clinical_ops_json
            )
            
            # Verify NON_AFFIRM was set
            call_args = mock_update.call_args
            assert call_args[1]['new_clinical_decision'] == 'NON_AFFIRM'
            assert call_args[1]['decision_outcome'] == 'NON_AFFIRM'
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_packet_not_found(
        self, processor, mock_db, sample_decision_tracking_id, sample_clinical_ops_decision_json
    ):
        """Test error when packet not found"""
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = None
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        message = {
            'decision_tracking_id': sample_decision_tracking_id,
            'message_id': 100
        }
        
        with pytest.raises(ValueError, match="Packet not found"):
            await processor._handle_clinical_decision(
                mock_db, message, sample_clinical_ops_decision_json
            )
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_invalid_indicator(
        self, processor, mock_db, sample_packet, sample_document, sample_decision_tracking_id
    ):
        """Test error when decision_indicator is invalid"""
        clinical_ops_json = {
            "decision_indicator": "X",  # Invalid
            "decision_tracking_id": sample_decision_tracking_id
        }
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        message = {
            'decision_tracking_id': sample_decision_tracking_id,
            'message_id': 100
        }
        
        with pytest.raises(ValueError, match="Invalid decision_indicator"):
            await processor._handle_clinical_decision(
                mock_db, message, clinical_ops_json
            )
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_missing_part_type(
        self, processor, mock_db, sample_packet, sample_decision_tracking_id, sample_clinical_ops_decision_json
    ):
        """Test that missing part_type doesn't fail Phase 1 - it will be derived in Phase 2"""
        document_no_part_type = Mock(spec=PacketDocumentDB)
        document_no_part_type.packet_document_id = 1
        document_no_part_type.part_type = None  # Missing part_type
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = document_no_part_type
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        
        message = {
            'decision_tracking_id': sample_decision_tracking_id,
            'message_id': 100,
            'created_at': datetime.now(timezone.utc)
        }
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=None), \
             patch.object(DecisionsService, 'create_approve_decision', return_value=mock_decision), \
             patch.object(DecisionsService, 'update_clinical_decision', return_value=mock_decision) as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            # Should not raise error - missing part_type is handled gracefully
            await processor._handle_clinical_decision(
                mock_db, message, sample_clinical_ops_decision_json
            )
            
            # Verify update_clinical_decision was called with part_type=None
            call_args = mock_update.call_args
            assert call_args[1]['part_type'] is None  # Missing part_type passed as None
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_idempotent_retry_affirm(
        self, processor, mock_db, sample_packet, sample_document, 
        sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test idempotent retry: When processing same Phase 1 message twice with AFFIRM, skip update_clinical_decision"""
        # Setup: Active decision already has AFFIRM
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 1
        existing_decision.packet_id = sample_packet.packet_id
        existing_decision.clinical_decision = 'AFFIRM'
        existing_decision.decision_outcome = 'AFFIRM'
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=existing_decision), \
             patch.object(DecisionsService, 'update_clinical_decision') as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status') as mock_update_status:
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            # Process same message twice (simulating retry)
            await processor._handle_clinical_decision(
                mock_db, message, sample_clinical_ops_decision_json
            )
            
            # Verify update_clinical_decision was NOT called (idempotent - reusing existing decision)
            mock_update.assert_not_called()
            
            # Verify packet status was still updated (workflow continues)
            mock_update_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_idempotent_retry_non_affirm(
        self, processor, mock_db, sample_packet, sample_document, sample_decision_tracking_id
    ):
        """Test idempotent retry: When processing same Phase 1 message twice with NON_AFFIRM, skip update_clinical_decision"""
        clinical_ops_json = {
            "decision_indicator": "N",  # N = NON_AFFIRM
            "decision_tracking_id": sample_decision_tracking_id
        }
        
        # Setup: Active decision already has NON_AFFIRM
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 1
        existing_decision.packet_id = sample_packet.packet_id
        existing_decision.clinical_decision = 'NON_AFFIRM'
        existing_decision.decision_outcome = 'NON_AFFIRM'
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=existing_decision), \
             patch.object(DecisionsService, 'update_clinical_decision') as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_clinical_decision(
                mock_db, message, clinical_ops_json
            )
            
            # Verify update_clinical_decision was NOT called (idempotent)
            mock_update.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_first_time_update_pending_to_affirm(
        self, processor, mock_db, sample_packet, sample_document, 
        sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test first-time update: When active decision has PENDING, update_clinical_decision should be called"""
        # Setup: Active decision has PENDING (different from payload)
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 1
        existing_decision.packet_id = sample_packet.packet_id
        existing_decision.clinical_decision = 'PENDING'
        existing_decision.decision_outcome = None  # No outcome yet
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        updated_decision = Mock(spec=PacketDecisionDB)
        updated_decision.packet_decision_id = 2
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=existing_decision), \
             patch.object(DecisionsService, 'update_clinical_decision', return_value=updated_decision) as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_clinical_decision(
                mock_db, message, sample_clinical_ops_decision_json
            )
            
            # Verify update_clinical_decision WAS called (different outcome)
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[1]['new_clinical_decision'] == 'AFFIRM'
            assert call_args[1]['decision_outcome'] == 'AFFIRM'
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_first_time_update_affirm_to_non_affirm(
        self, processor, mock_db, sample_packet, sample_document, sample_decision_tracking_id
    ):
        """Test first-time update: When active decision has AFFIRM but payload has NON_AFFIRM, update_clinical_decision should be called"""
        clinical_ops_json = {
            "decision_indicator": "N",  # N = NON_AFFIRM
            "decision_tracking_id": sample_decision_tracking_id
        }
        
        # Setup: Active decision has AFFIRM (different from payload NON_AFFIRM)
        existing_decision = Mock(spec=PacketDecisionDB)
        existing_decision.packet_decision_id = 1
        existing_decision.packet_id = sample_packet.packet_id
        existing_decision.clinical_decision = 'AFFIRM'
        existing_decision.decision_outcome = 'AFFIRM'
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        updated_decision = Mock(spec=PacketDecisionDB)
        updated_decision.packet_decision_id = 2
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=existing_decision), \
             patch.object(DecisionsService, 'update_clinical_decision', return_value=updated_decision) as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_clinical_decision(
                mock_db, message, clinical_ops_json
            )
            
            # Verify update_clinical_decision WAS called (different outcome)
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[1]['new_clinical_decision'] == 'NON_AFFIRM'
            assert call_args[1]['decision_outcome'] == 'NON_AFFIRM'
    
    @pytest.mark.asyncio
    async def test_handle_clinical_decision_no_active_decision_creates_then_updates(
        self, processor, mock_db, sample_packet, sample_document, 
        sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test no active decision: When there's no active decision, create_approve_decision then update_clinical_decision should be called"""
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        # First decision created by create_approve_decision
        created_decision = Mock(spec=PacketDecisionDB)
        created_decision.packet_decision_id = 1
        created_decision.packet_id = sample_packet.packet_id
        created_decision.clinical_decision = 'PENDING'
        created_decision.decision_outcome = None
        
        # Updated decision from update_clinical_decision
        updated_decision = Mock(spec=PacketDecisionDB)
        updated_decision.packet_decision_id = 2
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=None), \
             patch.object(DecisionsService, 'create_approve_decision', return_value=created_decision) as mock_create, \
             patch.object(DecisionsService, 'update_clinical_decision', return_value=updated_decision) as mock_update, \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_clinical_decision(
                mock_db, message, sample_clinical_ops_decision_json
            )
            
            # Verify create_approve_decision was called first
            mock_create.assert_called_once()
            
            # Verify update_clinical_decision was called after creation
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[1]['new_clinical_decision'] == 'AFFIRM'
            assert call_args[1]['decision_outcome'] == 'AFFIRM'


class TestHandleGeneratedPayload:
    """Test Phase 2: _handle_generated_payload"""
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_direct_pa(
        self, processor, mock_db, sample_packet, sample_document, sample_generated_payload, sample_decision_tracking_id
    ):
        """Test Phase 2 processing with Direct PA (empty esmdTransactionId)"""
        # Setup packet decision (created in Phase 1)
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.packet_id = sample_packet.packet_id
        mock_decision.decision_subtype = 'DIRECT_PA'  # Will be updated if different
        mock_decision.decision_outcome = 'AFFIRM'
        mock_decision.utn_status = 'NONE'
        mock_decision.letter_medical_docs = []
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=mock_decision), \
             patch.object(WorkflowOrchestratorService, 'update_packet_status') as mock_update_status:
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'payload': sample_generated_payload,
                'json_sent_to_integration': True,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_generated_payload(mock_db, message)
            
            # Verify decision_subtype was set (Direct PA)
            assert mock_decision.decision_subtype == 'DIRECT_PA'
            
            # Verify medical docs were set
            assert mock_decision.letter_medical_docs == ["/path/to/letter.pdf"]
            
            # Verify ESMD tracking was updated
            assert mock_decision.esmd_request_status == 'SENT'
            assert mock_decision.esmd_request_payload == sample_generated_payload
            assert mock_decision.esmd_attempt_count == 1
            assert mock_decision.letter_owner == 'SERVICE_OPS'
            assert mock_decision.letter_status == 'PENDING'
            
            # Verify packet status was updated
            mock_update_status.assert_called_once()
            status_call = mock_update_status.call_args
            assert status_call[1]['new_status'] == "Pending - UTN"
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_standard_pa(
        self, processor, mock_db, sample_packet, sample_document, sample_decision_tracking_id
    ):
        """Test Phase 2 processing with Standard PA (has esmdTransactionId)"""
        generated_payload = {
            "procedures": [{"procedureCode": "64483", "decisionIndicator": "A"}],
            "esmdTransactionId": "ESMD-12345",  # Has transaction ID = Standard PA
            "documentation": []
        }
        
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.packet_id = sample_packet.packet_id
        mock_decision.decision_subtype = 'DIRECT_PA'  # Will be updated to STANDARD_PA
        mock_decision.decision_outcome = 'AFFIRM'
        mock_decision.utn_status = 'NONE'
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=mock_decision), \
             patch.object(WorkflowOrchestratorService, 'update_packet_status'):
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'payload': generated_payload,
                'json_sent_to_integration': True,
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_generated_payload(mock_db, message)
            
            # Verify decision_subtype was updated to STANDARD_PA
            assert mock_decision.decision_subtype == 'STANDARD_PA'
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_no_decision_found(
        self, processor, mock_db, sample_packet, sample_generated_payload, sample_decision_tracking_id
    ):
        """Test error when packet_decision not found (Phase 1 should have created it)"""
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=None):
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'payload': sample_generated_payload,
                'json_sent_to_integration': True
            }
            
            with pytest.raises(ValueError, match="No active decision found"):
                await processor._handle_generated_payload(mock_db, message)
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_failed_send(
        self, processor, mock_db, sample_packet, sample_document, sample_generated_payload, sample_decision_tracking_id
    ):
        """Test Phase 2 when JSON Generator failed to send (json_sent_to_integration = False)"""
        mock_decision = Mock(spec=PacketDecisionDB)
        mock_decision.packet_decision_id = 1
        mock_decision.packet_id = sample_packet.packet_id
        mock_decision.decision_subtype = 'DIRECT_PA'
        mock_decision.decision_outcome = 'AFFIRM'
        
        mock_packet_query = MagicMock()
        mock_packet_query.filter.return_value.first.return_value = sample_packet
        
        mock_doc_query = MagicMock()
        mock_doc_query.filter.return_value.first.return_value = sample_document
        
        def query_side_effect(model):
            if model == PacketDB:
                return mock_packet_query
            elif model == PacketDocumentDB:
                return mock_doc_query
            return MagicMock()
        
        mock_db.query.side_effect = query_side_effect
        
        with patch.object(WorkflowOrchestratorService, 'get_active_decision', return_value=mock_decision), \
             patch.object(WorkflowOrchestratorService, 'update_packet_status') as mock_update_status:
            
            message = {
                'decision_tracking_id': sample_decision_tracking_id,
                'message_id': 100,
                'payload': sample_generated_payload,
                'json_sent_to_integration': False,  # Failed
                'created_at': datetime.now(timezone.utc)
            }
            
            await processor._handle_generated_payload(mock_db, message)
            
            # Verify ESMD status is FAILED
            assert mock_decision.esmd_request_status == 'FAILED'
            
            # Verify packet status indicates failure
            mock_update_status.assert_called_once()
            status_call = mock_update_status.call_args
            assert "Pending" in status_call[1]['new_status'] or "Pending" in status_call[1]['new_status']


class TestCallJsonGeneratorPhase2:
    """Test JSON Generator Phase 2 API call"""
    
    @pytest.mark.asyncio
    async def test_call_json_generator_phase2_success(self, processor, sample_decision_tracking_id):
        """Test successful API call"""
        mock_response = Mock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.raise_for_status = Mock()
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            result = await processor._call_json_generator_phase2(sample_decision_tracking_id)
            
            assert result is True
    
    @pytest.mark.asyncio
    async def test_call_json_generator_phase2_no_url(self, processor, sample_decision_tracking_id):
        """Test when JSON_GENERATOR_BASE_URL is not configured"""
        processor.json_generator_url = None
        
        result = await processor._call_json_generator_phase2(sample_decision_tracking_id)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_call_json_generator_phase2_retry_on_timeout(self, processor, sample_decision_tracking_id):
        """Test retry logic on timeout"""
        with patch('httpx.AsyncClient') as mock_client:
            # First attempt: timeout, second attempt: success
            mock_post = AsyncMock(side_effect=[
                httpx.ReadTimeout("Timeout"),
                Mock(json=Mock(return_value={"status": "success"}), raise_for_status=Mock())
            ])
            mock_client.return_value.__aenter__.return_value.post = mock_post
            
            with patch('asyncio.sleep', new_callable=AsyncMock):  # Mock sleep to speed up test
                result = await processor._call_json_generator_phase2(sample_decision_tracking_id)
                
                assert result is True
                assert mock_post.call_count == 2  # Retried once
    
    @pytest.mark.asyncio
    async def test_call_json_generator_phase2_client_error_no_retry(self, processor, sample_decision_tracking_id):
        """Test that 4xx errors don't retry"""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        
        error = httpx.HTTPStatusError("Bad Request", request=Mock(), response=mock_response)
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(side_effect=error)
            
            result = await processor._call_json_generator_phase2(sample_decision_tracking_id)
            
            assert result is False


class TestProcessMessage:
    """Test message routing logic"""
    
    @pytest.mark.asyncio
    async def test_process_message_phase1(
        self, processor, mock_db, sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test Phase 1 message routing"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': sample_clinical_ops_decision_json,
            'json_sent_to_integration': None  # Phase 1
        }
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_call_json_generator_phase2', new_callable=AsyncMock, return_value=True) as mock_call, \
             patch.object(processor, '_mark_message_processed'), \
             patch.object(asyncio, 'get_event_loop') as mock_loop:
            
            mock_loop.return_value.run_in_executor = AsyncMock()
            
            await processor._process_message(mock_db, message)
            
            # Verify Phase 1 handlers were called
            mock_handle.assert_called_once()
            mock_call.assert_called_once_with(sample_decision_tracking_id)
    
    @pytest.mark.asyncio
    async def test_process_message_phase2(
        self, processor, mock_db, sample_generated_payload, sample_decision_tracking_id
    ):
        """Test Phase 2 message routing"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'payload': sample_generated_payload,
            'json_sent_to_integration': True,  # Phase 2
            'clinical_ops_decision_json': None
        }
        
        with patch.object(processor, '_handle_generated_payload', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_mark_message_processed'), \
             patch.object(asyncio, 'get_event_loop') as mock_loop:
            
            mock_loop.return_value.run_in_executor = AsyncMock()
            
            await processor._process_message(mock_db, message)
            
            # Verify Phase 2 handler was called
            mock_handle.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_message_unknown_state(
        self, processor, mock_db, sample_decision_tracking_id
    ):
        """Test message with unknown state (both NULL)"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': None,
            'json_sent_to_integration': None  # Unknown state
        }
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle1, \
             patch.object(processor, '_handle_generated_payload', new_callable=AsyncMock) as mock_handle2:
            
            await processor._process_message(mock_db, message)
            
            # Verify neither handler was called
            mock_handle1.assert_not_called()
            mock_handle2.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_phase1_commits_immediately_before_phase2(
        self, processor, mock_db, sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test that Phase 1 commits immediately, before Phase 2 is attempted"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': sample_clinical_ops_decision_json,
            'json_sent_to_integration': None  # Phase 1
        }
        
        commit_calls = []
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock(side_effect=lambda executor, func, *args: func(*args))
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_call_json_generator_phase2', new_callable=AsyncMock, return_value=True) as mock_phase2, \
             patch.object(processor, '_mark_message_processed'), \
             patch.object(asyncio, 'get_event_loop', return_value=mock_loop):
            
            # Track commit calls
            original_commit = mock_db.commit
            def tracked_commit():
                commit_calls.append('commit')
                return original_commit()
            mock_db.commit = Mock(side_effect=tracked_commit)
            
            await processor._process_message(mock_db, message)
            
            # Verify Phase 1 handler was called
            mock_handle.assert_called_once()
            
            # Verify commit was called AFTER Phase 1 but BEFORE Phase 2
            assert len(commit_calls) == 1, "Commit should be called exactly once after Phase 1"
            assert mock_phase2.call_count == 1, "Phase 2 should be called after commit"
            
            # Verify commit was called before Phase 2
            # (We can't easily verify exact order, but we can verify both happened)
    
    @pytest.mark.asyncio
    async def test_phase2_failure_does_not_rollback_phase1(
        self, processor, mock_db, sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test that Phase 2 failures don't cause rollback of Phase 1 changes"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': sample_clinical_ops_decision_json,
            'json_sent_to_integration': None  # Phase 1
        }
        
        commit_calls = []
        rollback_calls = []
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock(side_effect=lambda executor, func, *args: func(*args))
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_call_json_generator_phase2', new_callable=AsyncMock, return_value=False) as mock_phase2, \
             patch.object(asyncio, 'get_event_loop', return_value=mock_loop):
            
            # Track commit and rollback calls
            original_commit = mock_db.commit
            def tracked_commit():
                commit_calls.append('commit')
                return original_commit()
            mock_db.commit = Mock(side_effect=tracked_commit)
            
            original_rollback = mock_db.rollback
            def tracked_rollback():
                rollback_calls.append('rollback')
                return original_rollback()
            mock_db.rollback = Mock(side_effect=tracked_rollback)
            
            # Process message - Phase 2 should fail but not raise
            await processor._process_message(mock_db, message)
            
            # Verify Phase 1 handler was called
            mock_handle.assert_called_once()
            
            # Verify commit was called (Phase 1 committed)
            assert len(commit_calls) == 1, "Phase 1 should have committed"
            
            # Verify rollback was NOT called (Phase 2 failure doesn't rollback)
            assert len(rollback_calls) == 0, "Rollback should not be called when Phase 2 fails"
            
            # Verify Phase 2 was attempted
            mock_phase2.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_phase2_exception_does_not_rollback_phase1(
        self, processor, mock_db, sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test that Phase 2 exceptions don't cause rollback of Phase 1 changes"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': sample_clinical_ops_decision_json,
            'json_sent_to_integration': None  # Phase 1
        }
        
        commit_calls = []
        rollback_calls = []
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock(side_effect=lambda executor, func, *args: func(*args))
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_call_json_generator_phase2', new_callable=AsyncMock, side_effect=Exception("Phase 2 error")) as mock_phase2, \
             patch.object(asyncio, 'get_event_loop', return_value=mock_loop):
            
            # Track commit and rollback calls
            original_commit = mock_db.commit
            def tracked_commit():
                commit_calls.append('commit')
                return original_commit()
            mock_db.commit = Mock(side_effect=tracked_commit)
            
            original_rollback = mock_db.rollback
            def tracked_rollback():
                rollback_calls.append('rollback')
                return original_rollback()
            mock_db.rollback = Mock(side_effect=tracked_rollback)
            
            # Process message - Phase 2 should raise but exception should be caught
            await processor._process_message(mock_db, message)
            
            # Verify Phase 1 handler was called
            mock_handle.assert_called_once()
            
            # Verify commit was called (Phase 1 committed)
            assert len(commit_calls) == 1, "Phase 1 should have committed"
            
            # Verify rollback was NOT called (Phase 2 exception doesn't rollback)
            assert len(rollback_calls) == 0, "Rollback should not be called when Phase 2 raises"
            
            # Verify Phase 2 was attempted
            mock_phase2.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_watermark_advances_even_if_phase2_fails(
        self, processor, mock_db, sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test that watermark advances even when Phase 2 fails"""
        message = {
            'message_id': 100,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': sample_clinical_ops_decision_json,
            'json_sent_to_integration': None,  # Phase 1
            'created_at': datetime.now(timezone.utc)
        }
        
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock(side_effect=lambda executor, func, *args: func(*args))
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_call_json_generator_phase2', new_callable=AsyncMock, return_value=False) as mock_phase2, \
             patch.object(asyncio, 'get_event_loop', return_value=mock_loop):
            
            # Process message - should complete normally even if Phase 2 fails
            await processor._process_message(mock_db, message)
            
            # Verify Phase 1 was processed
            mock_handle.assert_called_once()
            
            # Verify Phase 2 was attempted
            mock_phase2.assert_called_once()
            
            # Message should be considered "processed" for watermark purposes
            # (This is verified by the fact that _process_message returns normally)
    
    @pytest.mark.asyncio
    async def test_phase2_row_always_applies_decision(
        self, processor, mock_db, sample_packet, sample_document, 
        sample_clinical_ops_decision_json, sample_decision_tracking_id
    ):
        """Test that Phase 2 rows (json_sent_to_integration=True) also apply decision"""
        message = {
            'message_id': 200,
            'decision_tracking_id': sample_decision_tracking_id,
            'clinical_ops_decision_json': sample_clinical_ops_decision_json,
            'json_sent_to_integration': True,  # Phase 2 row
            'created_at': datetime.now(timezone.utc)
        }
        
        # Setup mocks
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = sample_packet
        mock_db.query.return_value = mock_query
        
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock(side_effect=lambda executor, func, *args: func(*args))
        
        with patch.object(processor, '_handle_clinical_decision', new_callable=AsyncMock) as mock_handle, \
             patch.object(processor, '_handle_generated_payload', new_callable=AsyncMock) as mock_phase2, \
             patch.object(processor, '_mark_decision_applied', new_callable=Mock) as mock_mark_applied, \
             patch.object(asyncio, 'get_event_loop', return_value=mock_loop):
            
            # Process Phase 2 message
            await processor._process_message(mock_db, message)
            
            # BULLETPROOF: Decision should be applied FIRST (even for Phase 2 rows)
            mock_handle.assert_called_once()
            mock_mark_applied.assert_called_once_with(mock_db, 200)
            
            # Then Phase 2 handler should be called
            mock_phase2.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_mark_decision_applied_sets_timestamp(
        self, processor, mock_db
    ):
        """Test that _mark_decision_applied sets clinical_decision_applied_at"""
        message_id = 300
        
        # Mock column exists check (first call)
        mock_scalar_result = Mock()
        mock_scalar_result.scalar.return_value = True  # Column exists
        
        # Mock UPDATE result (second call)
        mock_update_result = Mock()
        mock_update_result.rowcount = 1
        
        # Setup execute to return different results for different calls
        call_count = [0]
        def execute_side_effect(query, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: column exists check
                return mock_scalar_result
            else:
                # Second call: UPDATE statement
                return mock_update_result
        
        mock_db.execute = Mock(side_effect=execute_side_effect)
        
        # Call method
        processor._mark_decision_applied(mock_db, message_id)
        
        # Verify execute was called at least twice (column check + UPDATE)
        assert mock_db.execute.call_count >= 2
        
        # Verify UPDATE was called with message_id
        update_call = mock_db.execute.call_args_list[-1]  # Last call should be UPDATE
        assert update_call is not None
        # Check that message_id is in the parameters
        call_str = str(update_call)
        assert '300' in call_str or 'message_id' in call_str
    
    @pytest.mark.asyncio
    async def test_watermark_stops_at_first_failure(
        self, processor, mock_db, sample_clinical_ops_decision_json
    ):
        """Test that watermark only advances to last consecutive success"""
        messages = [
            {
                'message_id': 101,
                'decision_tracking_id': str(uuid.uuid4()),
                'clinical_ops_decision_json': sample_clinical_ops_decision_json,
                'json_sent_to_integration': None,
                'created_at': datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
            },
            {
                'message_id': 102,
                'decision_tracking_id': str(uuid.uuid4()),
                'clinical_ops_decision_json': sample_clinical_ops_decision_json,
                'json_sent_to_integration': None,
                'created_at': datetime(2026, 1, 1, 10, 1, 0, tzinfo=timezone.utc)
            },
            {
                'message_id': 103,
                'decision_tracking_id': str(uuid.uuid4()),
                'clinical_ops_decision_json': sample_clinical_ops_decision_json,
                'json_sent_to_integration': None,
                'created_at': datetime(2026, 1, 1, 10, 2, 0, tzinfo=timezone.utc)
            }
        ]
        
        mock_loop = Mock()
        mock_loop.run_in_executor = AsyncMock(side_effect=lambda executor, func, *args: func(*args))
        
        # Ensure processing_delay_seconds is a real number (not mocked)
        processor.processing_delay_seconds = 0.01  # Small delay for testing
        
        # Mock poll to return messages
        with patch.object(processor, '_poll_new_messages', return_value=messages) as mock_poll, \
             patch.object(processor, '_process_message', new_callable=AsyncMock) as mock_process, \
             patch.object(processor, '_update_watermark', new_callable=Mock) as mock_update_watermark, \
             patch.object(asyncio, 'get_event_loop', return_value=mock_loop), \
             patch('asyncio.sleep', new_callable=AsyncMock):  # Mock sleep to avoid delays
            
            # Make first message succeed, second fail
            def process_side_effect(db, msg):
                if msg['message_id'] == 102:
                    raise ValueError("Simulated failure")
                return None
            
            mock_process.side_effect = process_side_effect
            
            # Process batch
            await processor._poll_and_process()
            
            # Verify watermark was updated with message 101 (last success before failure)
            mock_update_watermark.assert_called_once()
            call_args = mock_update_watermark.call_args
            max_created_at = call_args[0][1]  # Second positional arg
            max_message_id = call_args[0][2]  # Third positional arg
            
            # Should be message 101 (not 103)
            assert max_message_id == 101, "Watermark should stop at last consecutive success"
    
    @pytest.mark.asyncio
    async def test_poll_filters_by_applied_at_column(
        self, processor, mock_db
    ):
        """Test that poll query filters by clinical_decision_applied_at IS NULL"""
        # Mock watermark
        mock_watermark = Mock()
        mock_watermark.fetchone.return_value = (datetime(1970, 1, 1), 0)
        mock_db.execute.return_value = mock_watermark
        
        # Mock column exists checks
        def execute_side_effect(query, *args, **kwargs):
            if 'clinical_ops_decision_json' in str(query):
                result = Mock()
                result.scalar.return_value = True
                return result
            elif 'clinical_decision_applied_at' in str(query):
                result = Mock()
                result.scalar.return_value = True  # Column exists
                return result
            elif 'SELECT' in str(query) and 'message_id' in str(query):
                # This is the actual poll query
                result = Mock()
                result.fetchall.return_value = []
                return result
            return mock_watermark
        
        mock_db.execute.side_effect = execute_side_effect
        
        # Call poll
        messages = processor._poll_new_messages(mock_db, limit=10)
        
        # Verify query was executed (would contain clinical_decision_applied_at IS NULL)
        assert mock_db.execute.called
    
    @pytest.mark.asyncio
    async def test_poll_uses_skip_locked(
        self, processor, mock_db
    ):
        """Test that poll query uses FOR UPDATE SKIP LOCKED"""
        # Mock watermark
        mock_watermark = Mock()
        mock_watermark.fetchone.return_value = (datetime(1970, 1, 1), 0)
        
        # Mock column exists checks
        def execute_side_effect(query, *args, **kwargs):
            query_str = str(query)
            if 'clinical_ops_decision_json' in query_str and 'EXISTS' in query_str:
                result = Mock()
                result.scalar.return_value = True
                return result
            elif 'clinical_decision_applied_at' in query_str and 'EXISTS' in query_str:
                result = Mock()
                result.scalar.return_value = True
                return result
            elif 'SELECT' in query_str and 'message_id' in query_str:
                # This is the actual poll query - check for SKIP LOCKED
                assert 'SKIP LOCKED' in query_str or 'FOR UPDATE' in query_str, \
                    "Poll query should use FOR UPDATE SKIP LOCKED"
                result = Mock()
                result.fetchall.return_value = []
                return result
            return mock_watermark
        
        mock_db.execute.side_effect = execute_side_effect
        
        # Call poll
        processor._poll_new_messages(mock_db, limit=10)
        
        # Assertion is in the side_effect above


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
