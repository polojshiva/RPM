"""
Unit tests for send_clinicalops is_picked and error_reason fields
Tests the new fields for ClinicalOps review workflow
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock
from sqlalchemy.orm import Session
import uuid

from app.models.send_clinicalops_db import SendClinicalOpsDB
from app.models.packet_db import PacketDB


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock(spec=Session)
    db.query = Mock()
    db.add = Mock()
    db.commit = Mock()
    db.refresh = Mock()
    db.flush = Mock()
    return db


@pytest.fixture
def sample_decision_tracking_id():
    """Sample decision tracking ID"""
    return str(uuid.uuid4())


@pytest.fixture
def sample_payload():
    """Sample payload for send_clinicalops"""
    return {
        "message_type": "CASE_READY_FOR_REVIEW",
        "decision_tracking_id": str(uuid.uuid4()),
        "packet_id": "SVC-2026-000001",
        "packet_data": {
            "beneficiary_name": "JOHN DOE",
            "beneficiary_mbi": "1AB2CD3EF45",
            "provider_name": "Test Provider",
            "provider_npi": "1234567890"
        }
    }


class TestSendClinicalOpsPickedFields:
    """Test is_picked and error_reason fields"""
    
    def test_model_has_is_picked_field(self):
        """Test that SendClinicalOpsDB model has is_picked field"""
        assert hasattr(SendClinicalOpsDB, 'is_picked')
        assert SendClinicalOpsDB.is_picked.nullable is True
    
    def test_model_has_error_reason_field(self):
        """Test that SendClinicalOpsDB model has error_reason field"""
        assert hasattr(SendClinicalOpsDB, 'error_reason')
        assert SendClinicalOpsDB.error_reason.nullable is True
    
    def test_create_record_with_default_is_picked(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test that new records have is_picked = NULL by default"""
        record = SendClinicalOpsDB(
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False
        )
        
        assert record.is_picked is None
        assert record.error_reason is None
    
    def test_create_record_with_is_picked_true(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test creating record with is_picked = TRUE (successfully picked)"""
        record = SendClinicalOpsDB(
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=True
        )
        
        assert record.is_picked is True
        assert record.error_reason is None
    
    def test_create_record_with_is_picked_false_and_error_reason(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test creating record with is_picked = FALSE and error_reason"""
        error_reason = "Missing HCPCS code"
        record = SendClinicalOpsDB(
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=False,
            error_reason=error_reason
        )
        
        assert record.is_picked is False
        assert record.error_reason == error_reason
    
    def test_update_record_to_mark_as_picked_with_error(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test updating record to mark as picked with error"""
        # Create initial record (not picked)
        record = SendClinicalOpsDB(
            message_id=1,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=None,
            error_reason=None
        )
        
        # Update to mark as picked with error
        record.is_picked = False
        record.error_reason = "Invalid provider NPI"
        
        assert record.is_picked is False
        assert record.error_reason == "Invalid provider NPI"
    
    def test_update_record_to_mark_as_picked_successfully(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test updating record to mark as picked successfully"""
        # Create initial record (not picked)
        record = SendClinicalOpsDB(
            message_id=1,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=None,
            error_reason=None
        )
        
        # Update to mark as picked successfully
        record.is_picked = True
        record.error_reason = None  # Clear any previous error
        
        assert record.is_picked is True
        assert record.error_reason is None
    
    def test_query_unreviewed_records(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test querying for unreviewed records (is_picked IS NULL)"""
        # Mock query to return unreviewed records
        unreviewed_record = SendClinicalOpsDB(
            message_id=1,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=None,
            error_reason=None
        )
        
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [unreviewed_record]
        mock_db.query.return_value = mock_query
        
        # Simulate query for unreviewed records
        results = mock_db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.is_picked.is_(None),
            SendClinicalOpsDB.is_deleted == False,
            SendClinicalOpsDB.message_status_id == 1
        ).all()
        
        assert len(results) == 1
        assert results[0].is_picked is None
        assert results[0].error_reason is None
    
    def test_query_rejected_records(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test querying for rejected records (is_picked = FALSE)"""
        # Mock query to return rejected records
        rejected_record = SendClinicalOpsDB(
            message_id=2,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=False,
            error_reason="Missing beneficiary DOB"
        )
        
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = [rejected_record]
        mock_db.query.return_value = mock_query
        
        # Simulate query for rejected records
        results = mock_db.query(SendClinicalOpsDB).filter(
            SendClinicalOpsDB.is_picked == False,
            SendClinicalOpsDB.is_deleted == False
        ).all()
        
        assert len(results) == 1
        assert results[0].is_picked is False
        assert results[0].error_reason == "Missing beneficiary DOB"
    
    def test_error_reason_max_length(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test that error_reason can handle reasonable length strings"""
        # Test with a long error reason (within 500 char limit)
        long_error = "Missing HCPCS code. Also missing provider fax number. Invalid beneficiary DOB format. " * 5  # ~300 chars
        
        record = SendClinicalOpsDB(
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=False,
            error_reason=long_error
        )
        
        assert record.error_reason == long_error
        assert len(record.error_reason) <= 500
    
    def test_multiple_error_scenarios(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test various error reason scenarios"""
        error_scenarios = [
            "Missing HCPCS code",
            "Invalid provider NPI",
            "Missing beneficiary DOB",
            "Invalid procedure code format",
            "Missing required documents"
        ]
        
        for error in error_scenarios:
            record = SendClinicalOpsDB(
                decision_tracking_id=sample_decision_tracking_id,
                payload=sample_payload,
                message_status_id=1,
                is_deleted=False,
                is_picked=False,
                error_reason=error
            )
            
            assert record.is_picked is False
            assert record.error_reason == error


class TestClinicalOpsWorkflow:
    """Test the ClinicalOps workflow with new fields"""
    
    def test_workflow_unreviewed_to_rejected(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test workflow: unreviewed → rejected with error"""
        # Step 1: Create unreviewed record
        record = SendClinicalOpsDB(
            message_id=1,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=None,
            error_reason=None
        )
        
        assert record.is_picked is None
        
        # Step 2: ClinicalOps reviews and finds error
        record.is_picked = False
        record.error_reason = "Missing HCPCS code"
        
        assert record.is_picked is False
        assert record.error_reason == "Missing HCPCS code"
    
    def test_workflow_unreviewed_to_success(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test workflow: unreviewed → successfully picked"""
        # Step 1: Create unreviewed record
        record = SendClinicalOpsDB(
            message_id=1,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=None,
            error_reason=None
        )
        
        assert record.is_picked is None
        
        # Step 2: ClinicalOps reviews and processes successfully
        record.is_picked = True
        record.error_reason = None
        
        assert record.is_picked is True
        assert record.error_reason is None
    
    def test_workflow_rejected_to_success_after_fix(self, mock_db, sample_decision_tracking_id, sample_payload):
        """Test workflow: rejected → fixed → successfully picked"""
        # Step 1: Create rejected record
        record = SendClinicalOpsDB(
            message_id=1,
            decision_tracking_id=sample_decision_tracking_id,
            payload=sample_payload,
            message_status_id=1,
            is_deleted=False,
            is_picked=False,
            error_reason="Missing HCPCS code"
        )
        
        assert record.is_picked is False
        assert record.error_reason == "Missing HCPCS code"
        
        # Step 2: Issue fixed, mark as successfully picked
        record.is_picked = True
        record.error_reason = None  # Clear error
        
        assert record.is_picked is True
        assert record.error_reason is None
