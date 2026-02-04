"""
Unit and Integration Tests for Intake Validation Workflow

Tests the complete workflow:
1. New packet (detailed_status = NULL) → not in Intake Validation count
2. User clicks "Validate" → detailed_status = "Intake Validation", assigned_to = user
3. User reviews → packet stays in "Intake Validation", lock maintained
4. User approves → detailed_status = "Clinical Review", assigned_to = NULL
5. User denies → detailed_status = "Closed - Dismissed", assigned_to = NULL
"""

import pytest
import sys
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.main import app
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.models.packet_dto import PacketHighLevelStatus


@pytest.fixture
def client():
    """Test client"""
    return TestClient(app)


@pytest.fixture
def mock_user():
    """Mock user for authentication"""
    user = Mock()
    user.email = "test@example.com"
    user.id = "user-123"
    return user


@pytest.fixture
def db_session():
    """Mock database session"""
    from unittest.mock import MagicMock
    session = MagicMock(spec=Session)
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    session.refresh = MagicMock()
    return session


@pytest.fixture
def sample_packet(db_session: Session):
    """Create a sample packet with NULL detailed_status (New)"""
    packet = PacketDB(
        external_id="PKT-2025-001",
        decision_tracking_id="550e8400-e29b-41d4-a716-446655440000",
        beneficiary_name="John Doe",
        beneficiary_mbi="1EG4TE5MK72",
        provider_name="Test Provider",
        provider_npi="1234567890",
        service_type="DME",
        received_date=datetime.now(timezone.utc),
        due_date=datetime.now(timezone.utc),
        detailed_status=None,  # NULL = New
        assigned_to=None,
    )
    db_session.add(packet)
    db_session.commit()
    db_session.refresh(packet)
    return packet


@pytest.fixture
def sample_document(db_session: Session, sample_packet: PacketDB):
    """Create a sample document for the packet"""
    document = PacketDocumentDB(
        packet_id=sample_packet.packet_id,
        external_id="DOC-001",
        file_name="test.pdf",
        file_size=1024,
        mime_type="application/pdf",
        split_status="DONE",
        ocr_status="DONE",
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


class TestStartIntakeValidation:
    """Tests for POST /api/packets/{id}/documents/{doc_id}/start-validation"""
    
    def test_start_validation_success(self, client, db_session, sample_packet, sample_document, mock_user):
        """Test successfully starting Intake Validation"""
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/documents/{sample_document.external_id}/start-validation"
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["detailedStatus"] == "Intake Validation"
        assert data["data"]["assignedTo"] == mock_user.email
        
        # Verify database
        db_session.refresh(sample_packet)
        assert sample_packet.detailed_status == "Intake Validation"
        assert sample_packet.assigned_to == mock_user.email
    
    def test_start_validation_already_assigned(self, client, db_session, sample_packet, sample_document, mock_user):
        """Test starting validation when packet is already assigned to another user"""
        # Assign to another user
        sample_packet.assigned_to = "other@example.com"
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/documents/{sample_document.external_id}/start-validation"
            )
        
        assert response.status_code == 403
        assert "assigned to" in response.json()["detail"].lower()
    
    def test_start_validation_already_in_validation(self, client, db_session, sample_packet, sample_document, mock_user):
        """Test starting validation when packet is already in Intake Validation"""
        sample_packet.detailed_status = "Intake Validation"
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/documents/{sample_document.external_id}/start-validation"
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["detailedStatus"] == "Intake Validation"
        # Should ensure assignment
        db_session.refresh(sample_packet)
        assert sample_packet.assigned_to == mock_user.email
    
    def test_start_validation_packet_not_found(self, client, mock_user):
        """Test starting validation for non-existent packet"""
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                "/api/packets/NONEXISTENT/documents/DOC-001/start-validation"
            )
        
        assert response.status_code == 404
    
    def test_start_validation_document_not_found(self, client, db_session, sample_packet, mock_user):
        """Test starting validation for non-existent document"""
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/documents/NONEXISTENT/start-validation"
            )
        
        assert response.status_code == 404


class TestClaimForReview:
    """Tests for POST /api/packets/{id}/claim-for-review"""
    
    def test_claim_for_review_success(self, client, db_session, sample_packet, mock_user):
        """Test successfully claiming packet for review"""
        sample_packet.detailed_status = "Intake Validation"
        sample_packet.assigned_to = None
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/claim-for-review"
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["assignedTo"] == mock_user.email
        
        # Verify database
        db_session.refresh(sample_packet)
        assert sample_packet.assigned_to == mock_user.email
    
    def test_claim_for_review_already_assigned(self, client, db_session, sample_packet, mock_user):
        """Test claiming when packet is already assigned to another user"""
        sample_packet.detailed_status = "Intake Validation"
        sample_packet.assigned_to = "other@example.com"
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/claim-for-review"
            )
        
        assert response.status_code == 403
        assert "assigned to" in response.json()["detail"].lower()
    
    def test_claim_for_review_already_assigned_to_self(self, client, db_session, sample_packet, mock_user):
        """Test claiming when packet is already assigned to current user"""
        sample_packet.detailed_status = "Intake Validation"
        sample_packet.assigned_to = mock_user.email
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.post(
                f"/api/packets/{sample_packet.external_id}/claim-for-review"
            )
        
        assert response.status_code == 200
        # Should succeed without error


class TestApproveDecision:
    """Tests for approve decision endpoint with status update"""
    
    def test_approve_releases_lock_and_sets_status(self, client, db_session, sample_packet, sample_document, mock_user):
        """Test that approve decision releases lock and sets Clinical Review status"""
        sample_packet.detailed_status = "Intake Validation"
        sample_packet.assigned_to = mock_user.email
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            with patch('app.services.decisions_service.DecisionsService.create_approve_decision') as mock_create:
                mock_decision = Mock()
                mock_decision.packet_decision_id = 1
                mock_decision.decision_type = "APPROVE"
                mock_decision.notes = None
                mock_decision.linked_validation_run_ids = None
                mock_decision.created_at = datetime.now(timezone.utc)
                mock_decision.created_by = mock_user.email
                mock_create.return_value = mock_decision
                
                response = client.post(
                    f"/api/packets/{sample_packet.external_id}/documents/{sample_document.external_id}/decisions/approve",
                    json={"notes": "Approved"}
                )
        
        assert response.status_code == 200
        
        # Verify database
        db_session.refresh(sample_packet)
        assert sample_packet.detailed_status == "Clinical Review"
        assert sample_packet.assigned_to is None  # Lock released
        assert sample_packet.validation_complete is True


class TestDismissalDecision:
    """Tests for dismissal decision endpoint with status update"""
    
    def test_dismissal_releases_lock_and_sets_status(self, client, db_session, sample_packet, sample_document, mock_user):
        """Test that dismissal decision releases lock and sets Closed - Dismissed status"""
        sample_packet.detailed_status = "Intake Validation"
        sample_packet.assigned_to = mock_user.email
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            with patch('app.services.decisions_service.DecisionsService.create_dismissal_decision') as mock_create:
                mock_decision = Mock()
                mock_decision.packet_decision_id = 1
                mock_decision.decision_type = "DISMISSAL"
                mock_decision.denial_reason = "MISSING_FIELDS"
                mock_decision.denial_details = {}
                mock_decision.notes = None
                mock_decision.linked_validation_run_ids = None
                mock_decision.created_at = datetime.now(timezone.utc)
                mock_decision.created_by = mock_user.email
                mock_create.return_value = mock_decision
                
                response = client.post(
                    f"/api/packets/{sample_packet.external_id}/documents/{sample_document.external_id}/decisions/dismissal",
                    json={
                        "denial_reason": "MISSING_FIELDS",
                        "denial_details": {},
                        "notes": "Dismissed"
                    }
                )
        
        assert response.status_code == 200
        
        # Verify database
        db_session.refresh(sample_packet)
        assert sample_packet.detailed_status == "Closed - Dismissed"
        assert sample_packet.assigned_to is None  # Lock released
        assert sample_packet.validation_complete is True
        assert sample_packet.closed_date is not None


class TestStatusCounts:
    """Tests for status count calculation"""
    
    def test_status_counts_exclude_null_status(self, client, db_session, mock_user):
        """Test that NULL detailed_status packets are not counted in Intake Validation"""
        # Create packets with different statuses
        packet1 = PacketDB(
            external_id="PKT-001",
            decision_tracking_id="550e8400-e29b-41d4-a716-446655440001",
            beneficiary_name="John Doe",
            beneficiary_mbi="1EG4TE5MK72",
            provider_name="Test Provider",
            provider_npi="1234567890",
            service_type="DME",
            received_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            detailed_status=None,  # NULL = New
        )
        packet2 = PacketDB(
            external_id="PKT-002",
            decision_tracking_id="550e8400-e29b-41d4-a716-446655440002",
            beneficiary_name="Jane Doe",
            beneficiary_mbi="1EG4TE5MK73",
            provider_name="Test Provider",
            provider_npi="1234567890",
            service_type="DME",
            received_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            detailed_status="Intake Validation",
        )
        packet3 = PacketDB(
            external_id="PKT-003",
            decision_tracking_id="550e8400-e29b-41d4-a716-446655440003",
            beneficiary_name="Bob Smith",
            beneficiary_mbi="1EG4TE5MK74",
            provider_name="Test Provider",
            provider_npi="1234567890",
            service_type="DME",
            received_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            detailed_status="Clinical Review",
        )
        
        db_session.add_all([packet1, packet2, packet3])
        db_session.commit()
        
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.get("/api/packets?page=1&page_size=10")
        
        assert response.status_code == 200
        data = response.json()
        status_counts = data["status_counts"]
        
        # NULL status should NOT be counted in Intake Validation
        assert status_counts["Intake Validation"] == 1  # Only packet2
        assert status_counts["Clinical Review"] == 1  # packet3
        # Total should be 3
        assert data["total"] == 3


class TestPacketConverter:
    """Tests for packet converter status mapping"""
    
    def test_null_status_maps_to_none(self, db_session):
        """Test that NULL detailed_status results in None high_level_status"""
        from app.utils.packet_converter import packet_to_dto
        
        packet = PacketDB(
            external_id="PKT-001",
            decision_tracking_id="550e8400-e29b-41d4-a716-446655440001",
            beneficiary_name="John Doe",
            beneficiary_mbi="1EG4TE5MK72",
            provider_name="Test Provider",
            provider_npi="1234567890",
            service_type="DME",
            received_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            detailed_status=None,  # NULL
        )
        db_session.add(packet)
        db_session.commit()
        
        dto = packet_to_dto(packet, db_session=db_session)
        
        # NULL status should result in None detailedStatus
        assert dto.detailedStatus is None
        # But highLevelStatus should default to INTAKE_VALIDATION for frontend compatibility
        assert dto.highLevelStatus == PacketHighLevelStatus.INTAKE_VALIDATION
    
    def test_intake_validation_status_maps_correctly(self, db_session):
        """Test that 'Intake Validation' detailed_status maps correctly"""
        from app.utils.packet_converter import packet_to_dto
        
        packet = PacketDB(
            external_id="PKT-001",
            decision_tracking_id="550e8400-e29b-41d4-a716-446655440001",
            beneficiary_name="John Doe",
            beneficiary_mbi="1EG4TE5MK72",
            provider_name="Test Provider",
            provider_npi="1234567890",
            service_type="DME",
            received_date=datetime.now(timezone.utc),
            due_date=datetime.now(timezone.utc),
            detailed_status="Intake Validation",
        )
        db_session.add(packet)
        db_session.commit()
        
        dto = packet_to_dto(packet, db_session=db_session)
        
        assert dto.detailedStatus == "Intake Validation"
        assert dto.highLevelStatus == PacketHighLevelStatus.INTAKE_VALIDATION



