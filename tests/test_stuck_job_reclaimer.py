"""
Unit tests for StuckJobReclaimer
Tests detection and recovery of stuck jobs.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from app.services.stuck_job_reclaimer import StuckJobReclaimer
from app.services.status_update_service import StatusUpdateService, StatusUpdateResult


class TestStuckJobReclaimer:
    """Test StuckJobReclaimer"""
    
    @pytest.fixture
    def status_service(self):
        """Create StatusUpdateService instance"""
        return StatusUpdateService(max_retries=3)
    
    @pytest.fixture
    def reclaimer(self, status_service):
        """Create StuckJobReclaimer instance"""
        return StuckJobReclaimer(
            stale_lock_minutes=10,
            max_attempts=5,
            status_update_service=status_service
        )
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = []
        session.commit.return_value = None
        return session
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_no_stuck_jobs(self, mock_session_local, reclaimer):
        """Test when no stuck jobs are detected (batch-based)"""
        mock_session = MagicMock()
        
        # COUNT query returns 0
        count_mock = MagicMock()
        count_mock.scalar.return_value = 0
        
        mock_session.execute.return_value = count_mock
        mock_session_local.return_value = mock_session
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        assert stats['detected'] == 0
        assert stats['reset_to_new'] == 0
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 0
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_reset_to_new_below_max_attempts(self, mock_session_local, reclaimer):
        """Test reset to NEW when attempt_count < max_attempts (batch-based)"""
        mock_session = MagicMock()
        
        # Step A1: COUNT query
        count_mock = MagicMock()
        count_mock.scalar.return_value = 1
        
        # Step A2: Batch reset returns 1 row
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = [
            (1, 2, datetime.now() - timedelta(minutes=15), 'decision-123')
        ]
        
        # Step A3: No max-attempts jobs
        failed_mock = MagicMock()
        failed_mock.fetchall.return_value = []
        
        mock_session.execute.side_effect = [count_mock, reset_mock, failed_mock]
        mock_session_local.return_value = mock_session
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        assert stats['detected'] == 1
        assert stats['reset_to_new'] == 1
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 0
        # Verify single commit for batch
        assert mock_session.commit.call_count == 1
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    @patch('app.services.stuck_job_reclaimer.StatusUpdateService')
    def test_mark_failed_at_max_attempts(self, mock_status_service_class, mock_session_local, reclaimer):
        """Test mark as FAILED when attempt_count >= max_attempts (atomic claim)"""
        mock_session = MagicMock()
        
        # Step A1: COUNT query
        count_mock = MagicMock()
        count_mock.scalar.return_value = 1
        
        # Step A2: Batch reset returns 0 (exceeds max attempts)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = []
        
        # Step A3: Atomic claim returns 1 job
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = [
            (1, 5, datetime.now() - timedelta(minutes=15), 'decision-123')
        ]
        
        mock_session.execute.side_effect = [count_mock, reset_mock, claim_mock]
        mock_session_local.return_value = mock_session
        
        # Mock status update service
        mock_status_service = MagicMock()
        mock_status_service.mark_failed_with_retry.return_value = StatusUpdateResult(
            success=True,
            attempts=1
        )
        reclaimer.status_update_service = mock_status_service
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        assert stats['detected'] == 1
        assert stats['reset_to_new'] == 0
        assert stats['marked_failed'] == 1
        assert stats['errors'] == 0
        # Verify status update service was called
        mock_status_service.mark_failed_with_retry.assert_called_once()
        call_kwargs = mock_status_service.mark_failed_with_retry.call_args[1]
        assert call_kwargs['inbox_id'] == 1
        assert call_kwargs['attempt_count'] == 5
        assert 'stuck' in call_kwargs['error_message'].lower()
        # Verify commit after atomic claim
        assert mock_session.commit.call_count == 1
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_multiple_stuck_jobs(self, mock_session_local, reclaimer):
        """Test recovery of multiple stuck jobs (batch-based)"""
        mock_session = MagicMock()
        
        # Step A1: COUNT query
        count_mock = MagicMock()
        count_mock.scalar.return_value = 3
        
        # Step A2: Batch reset returns 2 jobs (below max attempts)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = [
            (1, 2, datetime.now() - timedelta(minutes=15), 'decision-123'),
            (2, 3, datetime.now() - timedelta(minutes=20), 'decision-456')
        ]
        
        # Step A3: Atomic claim returns 1 job (exceeds max attempts)
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = [
            (3, 6, datetime.now() - timedelta(minutes=25), 'decision-789')
        ]
        
        mock_session.execute.side_effect = [count_mock, reset_mock, claim_mock]
        mock_session_local.return_value = mock_session
        
        # Mock status update service for third job
        mock_status_service = MagicMock()
        mock_status_service.mark_failed_with_retry.return_value = StatusUpdateResult(
            success=True,
            attempts=1
        )
        reclaimer.status_update_service = mock_status_service
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        assert stats['detected'] == 3
        assert stats['reset_to_new'] == 2
        assert stats['marked_failed'] == 1
        assert stats['errors'] == 0
        # Verify commits: 1 for reset batch, 1 for claim batch
        assert mock_session.commit.call_count == 2
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_error_handling(self, mock_session_local, reclaimer):
        """Test error handling during recovery"""
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception("Database error")
        mock_session_local.return_value = mock_session
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        assert stats['errors'] == 1
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_status_update_failure(self, mock_session_local, reclaimer):
        """Test handling when status update fails (batch-based)"""
        mock_session = MagicMock()
        
        # COUNT query returns 1
        count_mock = MagicMock()
        count_mock.scalar.return_value = 1
        
        # Batch reset returns 0 (exceeds max attempts)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = []
        
        # Atomic claim returns 1 job
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = [
            (1, 6, datetime.now() - timedelta(minutes=15), 'decision-123')
        ]
        
        mock_session.execute.side_effect = [count_mock, reset_mock, claim_mock]
        mock_session_local.return_value = mock_session
        
        # Mock status update service to fail
        mock_status_service = MagicMock()
        mock_status_service.mark_failed_with_retry.return_value = StatusUpdateResult(
            success=False,
            attempts=3,
            error="Status update failed"
        )
        reclaimer.status_update_service = mock_status_service
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        assert stats['detected'] == 1
        assert stats['marked_failed'] == 0  # Failed to mark
        assert stats['errors'] == 1  # Error recorded

