"""
Unit tests for StuckJobReclaimer - Atomic Batch-Based Implementation
Tests atomic batch updates, concurrency safety, and production scenarios.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta

from app.services.stuck_job_reclaimer import StuckJobReclaimer
from app.services.status_update_service import StatusUpdateService, StatusUpdateResult


class TestStuckJobReclaimerAtomic:
    """Test atomic batch-based StuckJobReclaimer"""
    
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
            batch_size=200,
            status_update_service=status_service
        )
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_batch_reset_atomic_single_commit(self, mock_session_local, reclaimer):
        """Test batch reset is atomic with single commit"""
        mock_session = MagicMock()
        
        # Step A1: COUNT query returns 5
        count_mock = MagicMock()
        count_mock.scalar.return_value = 5
        
        # Step A2: Batch reset returns 5 rows
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = [
            (1, 2, datetime.now() - timedelta(minutes=15), 'decision-123'),
            (2, 1, datetime.now() - timedelta(minutes=20), 'decision-456'),
            (3, 3, datetime.now() - timedelta(minutes=25), 'decision-789'),
            (4, 0, datetime.now() - timedelta(minutes=30), 'decision-abc'),
            (5, 2, datetime.now() - timedelta(minutes=35), 'decision-def')
        ]
        
        # Step A3: No max-attempts jobs
        failed_mock = MagicMock()
        failed_mock.fetchall.return_value = []
        
        mock_session.execute.side_effect = [count_mock, reset_mock, failed_mock]
        mock_session_local.return_value = mock_session
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        # Verify results
        assert stats['detected'] == 5
        assert stats['reset_to_new'] == 5
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 0
        
        # Verify single commit for batch reset
        assert mock_session.commit.call_count == 1  # One commit for batch reset
        assert mock_session.rollback.call_count == 1  # One rollback for empty failed candidates
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_batch_reset_only_stale_jobs(self, mock_session_local, reclaimer):
        """Test reclaimer doesn't reset non-stale jobs"""
        mock_session = MagicMock()
        
        # COUNT returns 3
        count_mock = MagicMock()
        count_mock.scalar.return_value = 3
        
        # Batch reset returns 0 (jobs no longer stale or already updated)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = []  # No rows updated (not stale anymore)
        
        # No max-attempts jobs
        failed_mock = MagicMock()
        failed_mock.fetchall.return_value = []
        
        mock_session.execute.side_effect = [count_mock, reset_mock, failed_mock]
        mock_session_local.return_value = mock_session
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        # Detected but none reset (no longer stale)
        assert stats['detected'] == 3
        assert stats['reset_to_new'] == 0
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 0
        
        # Verify rollback (no rows updated)
        assert mock_session.rollback.call_count >= 1
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_max_attempts_path_claims_jobs(self, mock_session_local, reclaimer):
        """Test max attempts path atomically claims jobs before marking FAILED"""
        mock_session = MagicMock()
        
        # COUNT returns 2
        count_mock = MagicMock()
        count_mock.scalar.return_value = 2
        
        # Batch reset returns 0 (all jobs exceed max attempts)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = []
        
        # Atomic claim returns 2 jobs
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = [
            (1, 5, datetime.now() - timedelta(minutes=15), 'decision-123'),
            (2, 6, datetime.now() - timedelta(minutes=20), 'decision-456')
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
        
        # Verify results
        assert stats['detected'] == 2
        assert stats['reset_to_new'] == 0
        assert stats['marked_failed'] == 2
        assert stats['errors'] == 0
        
        # Verify atomic claim happened (commit after claim)
        assert mock_session.commit.call_count == 1  # Commit after atomic claim
        
        # Verify mark_failed_with_retry called for each claimed job
        assert mock_status_service.mark_failed_with_retry.call_count == 2
        call_args_list = mock_status_service.mark_failed_with_retry.call_args_list
        assert call_args_list[0][1]['inbox_id'] == 1
        assert call_args_list[0][1]['attempt_count'] == 5
        assert call_args_list[1][1]['inbox_id'] == 2
        assert call_args_list[1][1]['attempt_count'] == 6
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_concurrency_simulation_second_reclaimer_sees_zero_rows(self, mock_session_local, reclaimer):
        """Test concurrency: second reclaimer sees rowcount=0 for already-claimed rows"""
        mock_session = MagicMock()
        
        # COUNT returns 1
        count_mock = MagicMock()
        count_mock.scalar.return_value = 1
        
        # Batch reset returns 0 (already claimed by another reclaimer)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = []
        
        # Atomic claim returns 0 (already claimed by another reclaimer)
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = []
        
        mock_session.execute.side_effect = [count_mock, reset_mock, claim_mock]
        mock_session_local.return_value = mock_session
        
        # Mock status update service to track calls
        mock_status_service = MagicMock()
        reclaimer.status_update_service = mock_status_service
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        # Detected but none processed (already claimed)
        assert stats['detected'] == 1
        assert stats['reset_to_new'] == 0
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 0
        
        # Verify no mark_failed calls (nothing claimed)
        assert mock_status_service.mark_failed_with_retry.call_count == 0
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_mark_failed_retry_failure_does_not_throw(self, mock_session_local, reclaimer):
        """Test that mark_failed failure doesn't throw from reclaimer loop"""
        mock_session = MagicMock()
        
        # COUNT returns 1
        count_mock = MagicMock()
        count_mock.scalar.return_value = 1
        
        # Batch reset returns 0
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = []
        
        # Atomic claim returns 1 job
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = [
            (1, 5, datetime.now() - timedelta(minutes=15), 'decision-123')
        ]
        
        mock_session.execute.side_effect = [count_mock, reset_mock, claim_mock]
        mock_session_local.return_value = mock_session
        
        # Mock status update service to fail after all retries
        mock_status_service = MagicMock()
        mock_status_service.mark_failed_with_retry.return_value = StatusUpdateResult(
            success=False,
            attempts=10,
            error="All retries failed"
        )
        reclaimer.status_update_service = mock_status_service
        
        # Should not throw
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        # Error recorded but reclaimer finished
        assert stats['detected'] == 1
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 1
        
        # Verify mark_failed was called
        assert mock_status_service.mark_failed_with_retry.call_count == 1
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_mixed_batch_reset_and_failed(self, mock_session_local, reclaimer):
        """Test mixed batch: some reset to NEW, some marked as FAILED"""
        mock_session = MagicMock()
        
        # COUNT returns 4
        count_mock = MagicMock()
        count_mock.scalar.return_value = 4
        
        # Batch reset returns 2 jobs (below max attempts)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = [
            (1, 2, datetime.now() - timedelta(minutes=15), 'decision-123'),
            (2, 3, datetime.now() - timedelta(minutes=20), 'decision-456')
        ]
        
        # Atomic claim returns 2 jobs (exceed max attempts)
        claim_mock = MagicMock()
        claim_mock.fetchall.return_value = [
            (3, 5, datetime.now() - timedelta(minutes=25), 'decision-789'),
            (4, 6, datetime.now() - timedelta(minutes=30), 'decision-abc')
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
        
        # Verify results
        assert stats['detected'] == 4
        assert stats['reset_to_new'] == 2
        assert stats['marked_failed'] == 2
        assert stats['errors'] == 0
        
        # Verify commits: 1 for reset batch, 1 for claim batch
        assert mock_session.commit.call_count == 2
        
        # Verify mark_failed called for each claimed job
        assert mock_status_service.mark_failed_with_retry.call_count == 2
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_reclaimer_id_uniqueness(self, mock_session_local, reclaimer):
        """Test that each reclaimer instance has unique ID"""
        reclaimer2 = StuckJobReclaimer(
            stale_lock_minutes=10,
            max_attempts=5,
            batch_size=200
        )
        
        # Verify reclaimer IDs are different
        assert reclaimer.reclaimer_id != reclaimer2.reclaimer_id
        assert reclaimer.reclaimer_id.startswith('reclaimer:')
        assert reclaimer2.reclaimer_id.startswith('reclaimer:')
    
    @patch('app.services.stuck_job_reclaimer.SessionLocal')
    def test_batch_size_limit(self, mock_session_local, reclaimer):
        """Test that batch_size limits number of jobs processed"""
        mock_session = MagicMock()
        
        # COUNT returns 500 (more than batch_size=200)
        count_mock = MagicMock()
        count_mock.scalar.return_value = 500
        
        # Batch reset returns 200 (limited by batch_size)
        reset_mock = MagicMock()
        reset_mock.fetchall.return_value = [
            (i, 2, datetime.now() - timedelta(minutes=15+i), f'decision-{i}')
            for i in range(1, 201)  # 200 rows
        ]
        
        # No max-attempts jobs
        failed_mock = MagicMock()
        failed_mock.fetchall.return_value = []
        
        mock_session.execute.side_effect = [count_mock, reset_mock, failed_mock]
        mock_session_local.return_value = mock_session
        
        stats = reclaimer.detect_and_recover_stuck_jobs()
        
        # Detected 500 but only 200 processed (batch_size limit)
        assert stats['detected'] == 500
        assert stats['reset_to_new'] == 200
        assert stats['marked_failed'] == 0
        assert stats['errors'] == 0

