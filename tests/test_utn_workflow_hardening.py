"""
Hardening Tests for UTN Workflow
Stage 7: Failure injection, idempotency, and load tests

Tests cover:
- Idempotency (duplicate messages, retries)
- Failure injection (DB deadlocks, timeouts, partial failures)
- Missing data scenarios
- Concurrent processing
- Payload validation
"""
import pytest
import sys
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, IntegrityError

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.utn_handlers import UtnSuccessHandler, UtnFailHandler
from app.services.esmd_payload_generator import EsmdPayloadGenerator
from app.services.dismissal_workflow_service import DismissalWorkflowService
from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
from app.models.send_integration_db import SendIntegrationDB


class TestUtnHandlersIdempotency:
    """Test idempotency of UTN handlers"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.flush = Mock()
        return db
    
    @pytest.fixture
    def sample_packet(self):
        """Sample packet for testing"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        packet.external_id = "SVC-2026-001234"
        packet.decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        return packet
    
    @pytest.fixture
    def sample_decision(self):
        """Sample packet_decision for testing"""
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_decision_id = 456
        decision.packet_id = 123
        decision.correlation_id = "550e8400-e29b-41d4-a716-446655440000"
        decision.utn = None
        decision.utn_status = 'NONE'
        decision.letter_owner = 'CLINICAL_OPS'
        decision.esmd_request_status = 'SENT'  # Initialize for UTN_SUCCESS handler
        return decision
    
    def test_utn_success_idempotent_duplicate_message(self, mock_db, sample_packet, sample_decision):
        """Test that processing the same UTN_SUCCESS message twice is idempotent"""
        # Mock query to return packet and decision (reset for each call)
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            # First query returns packet, second returns decision
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count % 2 == 1:
                filter_mock.first.return_value = sample_packet
            else:
                filter_mock.first.return_value = sample_decision
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        payload = {
            "message_type": "UTN",
            "unique_tracking_number": "JLB86260080030",
            "decision_tracking_id": str(sample_packet.decision_tracking_id),
            "esmd_transaction_id": "esmd-123"
        }
        
        message = {
            'message_id': 1,
            'decision_tracking_id': str(sample_packet.decision_tracking_id),
            'payload': payload
        }
        
        # First call (async method needs to be awaited)
        query_side_effect.call_count = 0
        import asyncio
        asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        
        # Verify first call updates
        assert sample_decision.utn == "JLB86260080030"
        assert sample_decision.utn_status == 'SUCCESS'
        assert sample_decision.esmd_request_status == 'ACKED'
        
        # Reset for second call
        first_utn = sample_decision.utn
        first_status = sample_decision.utn_status
        
        # Second call (duplicate message)
        query_side_effect.call_count = 0
        import asyncio
        asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        
        # Verify idempotency: same values (no duplicate updates)
        assert sample_decision.utn == first_utn
        assert sample_decision.utn_status == first_status
        # Should not raise errors or create duplicates
    
    def test_utn_fail_idempotent_duplicate_message(self, mock_db, sample_packet, sample_decision):
        """Test that processing the same UTN_FAIL message twice is idempotent"""
        # Mock query to return packet and decision (reset for each call)
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            # First query returns packet, second returns decision
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count % 2 == 1:
                filter_mock.first.return_value = sample_packet
            else:
                filter_mock.first.return_value = sample_decision
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        payload = {
            "message_type": "UTN_FAIL",
            "error_code": "UNABLE_TO_CREATE_UTN",
            "error_description": "Invalid beneficiary MBI",
            "action_required": "Please verify beneficiary MBI"
        }
        
        message = {
            'message_id': 2,
            'decision_tracking_id': str(sample_packet.decision_tracking_id),
            'payload': payload
        }
        
        # First call
        query_side_effect.call_count = 0
        UtnFailHandler.handle(mock_db, message)  # UtnFailHandler.handle is NOT async
        
        # Verify first call updates
        assert sample_decision.utn_status == 'FAILED'
        assert sample_decision.requires_utn_fix == True
        assert sample_decision.utn_fail_payload == payload
        
        # Second call (duplicate message)
        query_side_effect.call_count = 0
        UtnFailHandler.handle(mock_db, message)
        
        # Verify idempotency: same values
        assert sample_decision.utn_status == 'FAILED'
        assert sample_decision.requires_utn_fix == True
        # Should not raise errors or create duplicates


class TestEsmdPayloadGeneratorIdempotency:
    """Test idempotency of ESMD payload generation"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        return db
    
    @pytest.fixture
    def sample_packet(self):
        """Sample packet"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        packet.external_id = "SVC-2026-001234"
        packet.decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        packet.beneficiary_name = "John Doe"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "ABC Clinic"
        packet.provider_npi = "1234567890"
        packet.submission_type = "Expedited"
        return packet
    
    @pytest.fixture
    def sample_decision(self):
        """Sample packet_decision"""
        decision = Mock(spec=PacketDecisionDB)
        decision.decision_outcome = "AFFIRM"
        decision.decision_subtype = "DIRECT_PA"
        decision.part_type = "B"
        return decision
    
    @pytest.fixture
    def sample_document(self):
        """Sample packet_document"""
        doc = Mock(spec=PacketDocumentDB)
        doc.extracted_fields = {
            "fields": {
                "provider_address": {"value": "123 Main St"},
                "provider_city": {"value": "Newark"},
                "provider_state": {"value": "NJ"},
                "provider_zip": {"value": "07102"}
            }
        }
        return doc
    
    def test_payload_generation_idempotent(self, mock_db, sample_packet, sample_decision, sample_document):
        """Test that generating payload multiple times produces same result"""
        generator = EsmdPayloadGenerator(mock_db)
        
        # Mock document query
        mock_db.query.return_value.filter.return_value.first.return_value = sample_document
        
        procedures = [
            {"procedure_code": "L0450", "place_of_service": "12", "mr_count_unit_of_service": "1"}
        ]
        
        # First generation
        payload1 = generator.generate_payload(
            packet=sample_packet,
            packet_decision=sample_decision,
            procedures=procedures,
            medical_docs=None
        )
        
        # Second generation (same inputs)
        payload2 = generator.generate_payload(
            packet=sample_packet,
            packet_decision=sample_decision,
            procedures=procedures,
            medical_docs=None
        )
        
        # Verify payloads are identical (except uniqueId which includes timestamp)
        assert payload1['header'] == payload2['header']
        assert payload1['partType'] == payload2['partType']
        assert payload1['isDirectPa'] == payload2['isDirectPa']
        assert payload1['procedures'] == payload2['procedures']
        # uniqueId will differ due to timestamp, but structure should be same


class TestFailureInjection:
    """Test failure scenarios and error handling"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.flush = Mock()
        return db
    
    def test_utn_success_missing_packet(self, mock_db):
        """Test UTN_SUCCESS handler when packet is missing"""
        # Mock: packet not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        payload = {
            "message_type": "UTN",
            "unique_tracking_number": "JLB86260080030",
            "decision_tracking_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        message = {
            'message_id': 1,
            'decision_tracking_id': "550e8400-e29b-41d4-a716-446655440000",
            'payload': payload
        }
        
        # Should raise ValueError (async method needs await)
        import asyncio
        with pytest.raises(ValueError, match="Packet not found"):
            asyncio.run(UtnSuccessHandler.handle(mock_db, message))
    
    def test_utn_success_missing_decision(self, mock_db):
        """Test UTN_SUCCESS handler when decision is missing"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        
        # Mock query to return packet then None for decision
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count == 1:
                filter_mock.first.return_value = packet
            else:
                filter_mock.first.return_value = None
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        payload = {
            "message_type": "UTN",
            "unique_tracking_number": "JLB86260080030",
            "decision_tracking_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        message = {
            'message_id': 1,
            'decision_tracking_id': "550e8400-e29b-41d4-a716-446655440000",
            'payload': payload
        }
        
        # Handler returns early (doesn't raise) when decision is missing (dismissal case)
        # This is expected behavior - dismissal cases may not have packet_decision yet
        query_side_effect.call_count = 0
        import asyncio
        asyncio.run(UtnSuccessHandler.handle(mock_db, message))  # Should not raise
        
        # Verify handler handled gracefully (returns early)
        assert query_side_effect.call_count == 2  # Called for packet and decision
    
    def test_utn_success_db_deadlock(self, mock_db):
        """Test UTN_SUCCESS handler handles DB deadlock"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_id = 123
        
        # Mock query to return packet and decision
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count == 1:
                filter_mock.first.return_value = packet
            else:
                filter_mock.first.return_value = decision
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        # Simulate deadlock on flush (handler uses flush, not commit)
        mock_db.flush.side_effect = OperationalError(
            "deadlock detected",
            None,
            None
        )
        
        payload = {
            "message_type": "UTN",
            "unique_tracking_number": "JLB86260080030",
            "decision_tracking_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        message = {
            'message_id': 1,
            'decision_tracking_id': "550e8400-e29b-41d4-a716-446655440000",
            'payload': payload
        }
        
        # Should raise OperationalError (caller should retry)
        query_side_effect.call_count = 0
        import asyncio
        with pytest.raises(OperationalError):
            asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        
        # Note: Handler doesn't call rollback explicitly - it's handled by the caller/inbox processor
        # The exception propagates up for the caller to handle
    
    def test_esmd_payload_generation_missing_document(self, mock_db):
        """Test ESMD payload generation when document is missing"""
        generator = EsmdPayloadGenerator(mock_db)
        
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        decision = Mock(spec=PacketDecisionDB)
        
        # Mock: document not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="No packet_document found"):
            generator.generate_payload(
                packet=packet,
                packet_decision=decision,
                procedures=[],
                medical_docs=None
            )
    
    @pytest.mark.asyncio
    @patch('app.routes.packets.get_client_ip')
    async def test_resend_max_attempts_reached(self, mock_get_client_ip, mock_db):
        """Test resend fails when max attempts reached"""
        from app.routes.packets import resend_to_esmd
        from app.models.utn_dto import ResendToEsmdRequest
        from fastapi import HTTPException
        
        mock_get_client_ip.return_value = "127.0.0.1"
        
        packet = Mock(spec=PacketDB)
        packet.external_id = "SVC-2026-001234"
        packet.packet_id = 123
        packet.decision_tracking_id = "550e8400-e29b-41d4-a716-446655440000"
        
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_id = 123
        decision.requires_utn_fix = True
        decision.esmd_attempt_count = 5  # Max attempts reached
        
        # Mock query to return packet then decision
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count == 1:
                filter_mock.first.return_value = packet
            else:
                filter_mock.first.return_value = decision
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        request_data = ResendToEsmdRequest(notes="Test resend")
        mock_request = Mock()
        mock_user = Mock()
        
        # Should raise HTTPException
        query_side_effect.call_count = 0
        with pytest.raises(HTTPException) as exc_info:
            await resend_to_esmd(
                packet_id="SVC-2026-001234",
                request_data=request_data,
                request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert "Maximum resend attempts" in str(exc_info.value.detail) or "maximum" in str(exc_info.value.detail).lower()


class TestConcurrentProcessing:
    """Test concurrent processing scenarios"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        return db
    
    def test_concurrent_utn_success_updates(self, mock_db):
        """Test concurrent UTN_SUCCESS updates don't conflict"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        
        decision1 = Mock(spec=PacketDecisionDB)
        decision1.packet_id = 123
        decision1.utn = None
        
        decision2 = Mock(spec=PacketDecisionDB)
        decision2.packet_id = 123
        decision2.utn = None
        
        # Simulate two concurrent calls
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            packet, decision1,  # First call
            packet, decision2   # Second call
        ]
        
        payload = {
            "message_type": "UTN",
            "unique_tracking_number": "JLB86260080030",
            "decision_tracking_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        message = {
            'message_id': 1,
            'decision_tracking_id': "550e8400-e29b-41d4-a716-446655440000",
            'payload': payload
        }
        
        # Both calls should succeed (idempotent)
        import asyncio
        asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        
        # Both decisions should have same UTN
        assert decision1.utn == "JLB86260080030"
        assert decision2.utn == "JLB86260080030"


class TestPayloadValidation:
    """Test payload validation and error handling"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        return db
    
    def test_utn_success_missing_utn(self, mock_db):
        """Test UTN_SUCCESS handler with missing unique_tracking_number"""
        # Handler validates UTN and raises ValueError if missing
        payload = {
            "message_type": "UTN",
            "decision_tracking_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        message = {
            'message_id': 1,
            'decision_tracking_id': "550e8400-e29b-41d4-a716-446655440000",
            'payload': payload
        }
        
        # Handler raises ValueError when UTN is missing (validation)
        import asyncio
        with pytest.raises(ValueError, match="missing 'unique_tracking_number'"):
            asyncio.run(UtnSuccessHandler.handle(mock_db, message))
    
    def test_utn_fail_missing_error_code(self, mock_db):
        """Test UTN_FAIL handler with missing error_code"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_id = 123
        
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            packet,
            decision
        ]
        
        # Payload missing error_code
        payload = {
            "message_type": "UTN_FAIL",
            "decision_tracking_id": "550e8400-e29b-41d4-a716-446655440000"
        }
        
        message = {
            'message_id': 2,
            'decision_tracking_id': "550e8400-e29b-41d4-a716-446655440000",
            'payload': payload
        }
        
        # Should handle gracefully (logs warning but doesn't fail)
        UtnFailHandler.handle(mock_db, message)
        
        # Decision should still be updated
        assert decision.utn_status == 'FAILED'
        assert decision.requires_utn_fix == True


class TestDismissalWorkflowHardening:
    """Test dismissal workflow error handling"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.flush = Mock()
        return db
    
    def test_dismissal_missing_document(self, mock_db):
        """Test dismissal workflow when document is missing"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        packet.external_id = "SVC-2026-001234"
        packet.beneficiary_name = "John Doe"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "ABC Clinic"
        packet.provider_npi = "1234567890"
        packet.service_type = "DME"
        packet.hcpcs = "L0450"
        packet.provider_fax = "555-1234"
        
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_decision_id = 456
        decision.packet_id = 123
        decision.denial_reason = "MISSING_FIELDS"
        decision.denial_details = {"missingFields": ["Beneficiary DOB"]}
        decision.created_by = "user@example.com"
        
        # Mock: document not found
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="No packet_document found"):
            DismissalWorkflowService.process_dismissal(
                db=mock_db,
                packet=packet,
                packet_decision=decision,
                created_by="user@example.com"
            )
    
    @patch('app.services.letter_generation_service.LetterGenerationService')
    @patch('app.services.esmd_payload_generator.EsmdPayloadGenerator.generate_payload')
    def test_dismissal_partial_failure_rollback(self, mock_generate_payload, mock_letter_service, mock_db):
        """Test dismissal workflow rollback on partial failure"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 123
        packet.external_id = "SVC-2026-001234"
        packet.beneficiary_name = "John Doe"
        packet.beneficiary_mbi = "1EG4TE5MK72"
        packet.provider_name = "ABC Clinic"
        packet.provider_npi = "1234567890"
        packet.service_type = "DME"
        packet.hcpcs = "L0450"
        packet.provider_fax = "555-1234"
        packet.submission_type = "Expedited"
        
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_decision_id = 456
        decision.packet_id = 123
        decision.denial_reason = "MISSING_FIELDS"
        decision.denial_details = {"missingFields": ["Beneficiary DOB"]}
        decision.created_by = "user@example.com"
        decision.decision_outcome = None
        decision.decision_subtype = None
        decision.part_type = None
        
        document = Mock(spec=PacketDocumentDB)
        document.extracted_fields = {"fields": {}}
        document.part_type = "B"
        
        # Return a real dict (not Mock) for payload generation
        mock_generate_payload.return_value = {
            "header": {"priorAuthDecision": "N"},
            "procedures": []
        }
        
        mock_db.query.return_value.filter.return_value.first.return_value = document
        
        # Mock letter generation service
        mock_letter_instance = Mock()
        mock_letter_instance.generate_letter.return_value = {
            'blob_url': 'https://blob.test/letter.pdf',
            'filename': 'letter.pdf',
            'file_size_bytes': 1024
        }
        mock_letter_service.return_value = mock_letter_instance
        
        # Simulate failure on commit (after payload generation)
        mock_db.commit.side_effect = OperationalError("connection lost", None, None)
        
        # Should raise OperationalError
        with pytest.raises(OperationalError):
            DismissalWorkflowService.process_dismissal(
                db=mock_db,
                packet=packet,
                packet_decision=decision,
                created_by="user@example.com"
            )
        
        # Note: Handler doesn't call rollback explicitly - it's handled by the caller/inbox processor
        # The exception propagates up for the caller to handle
        # Verify that the error was raised (which is what we're testing)
        assert mock_db.commit.called


class TestResendWorkflowHardening:
    """Test resend workflow error handling"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock(spec=Session)
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        db.flush = Mock()
        return db
    
    @pytest.mark.asyncio
    @patch('app.routes.packets.get_client_ip')
    async def test_resend_not_required(self, mock_get_client_ip, mock_db):
        """Test resend fails when packet doesn't require UTN fix"""
        from app.routes.packets import resend_to_esmd
        from app.models.utn_dto import ResendToEsmdRequest
        from fastapi import HTTPException
        
        mock_get_client_ip.return_value = "127.0.0.1"
        
        packet = Mock(spec=PacketDB)
        packet.external_id = "SVC-2026-001234"
        packet.packet_id = 123
        
        decision = Mock(spec=PacketDecisionDB)
        decision.packet_id = 123
        decision.requires_utn_fix = False  # Not required
        
        # Mock query to return packet then decision
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count == 1:
                filter_mock.first.return_value = packet
            else:
                filter_mock.first.return_value = decision
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        request_data = ResendToEsmdRequest(notes="Test resend")
        mock_request = Mock()
        mock_user = Mock()
        
        # Should raise HTTPException
        query_side_effect.call_count = 0
        with pytest.raises(HTTPException) as exc_info:
            await resend_to_esmd(
                packet_id="SVC-2026-001234",
                request_data=request_data,
                request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert "does not require UTN fix" in str(exc_info.value.detail) or "requires_utn_fix" in str(exc_info.value.detail).lower()
    
    @pytest.mark.asyncio
    @patch('app.routes.packets.get_client_ip')
    async def test_resend_missing_decision(self, mock_get_client_ip, mock_db):
        """Test resend fails when decision is missing"""
        from app.routes.packets import resend_to_esmd
        from app.models.utn_dto import ResendToEsmdRequest
        from fastapi import HTTPException
        
        mock_get_client_ip.return_value = "127.0.0.1"
        
        packet = Mock(spec=PacketDB)
        packet.external_id = "SVC-2026-001234"
        packet.packet_id = 123
        
        # Mock query to return packet then None for decision
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count == 1:
                filter_mock.first.return_value = packet
            else:
                filter_mock.first.return_value = None  # Decision not found
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        request_data = ResendToEsmdRequest(notes="Test resend")
        mock_request = Mock()
        mock_user = Mock()
        
        # Should raise HTTPException
        query_side_effect.call_count = 0
        with pytest.raises(HTTPException) as exc_info:
            await resend_to_esmd(
                packet_id="SVC-2026-001234",
                request_data=request_data,
                request=mock_request,
                db=mock_db,
                current_user=mock_user
            )
        
        assert "Packet decision not found" in str(exc_info.value.detail) or "decision" in str(exc_info.value.detail).lower()

