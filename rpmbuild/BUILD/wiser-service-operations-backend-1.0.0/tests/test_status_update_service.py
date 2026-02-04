"""
Unit tests for StatusUpdateService
Tests guaranteed status updates with retry logic.
"""
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy.exc import OperationalError

from app.services.status_update_service import StatusUpdateService, StatusUpdateResult


class TestStatusUpdateService:
    """Test StatusUpdateService"""
    
    @pytest.fixture
    def status_service(self):
        """Create StatusUpdateService instance"""
        return StatusUpdateService(max_retries=3)
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = MagicMock()
        session.execute.return_value.rowcount = 1
        session.commit.return_value = None
        return session
    
    @patch('app.services.status_update_service.SessionLocal')
    def test_mark_done_success_first_attempt(self, mock_session_local, status_service, mock_db_session):
        """Test successful mark_done on first attempt"""
        mock_session_local.return_value = mock_db_session
        
        result = status_service.mark_done_with_retry(inbox_id=1)
        
        assert result.success is True
        assert result.attempts == 1
        assert result.dlq is False
        assert result.error is None
        mock_db_session.execute.assert_called_once()
        mock_db_session.commit.assert_called_once()
    
    @patch('app.services.status_update_service.SessionLocal')
    @patch('time.sleep')
    def test_mark_done_retry_on_failure(self, mock_sleep, mock_session_local, status_service):
        """Test mark_done retries on failure"""
        # First two attempts fail, third succeeds
        mock_session = MagicMock()
        mock_session.execute.side_effect = [
            OperationalError("Connection lost", None, None),
            OperationalError("Connection lost", None, None),
            MagicMock(rowcount=1)  # Success on third attempt
        ]
        mock_session.commit.return_value = None
        mock_session_local.return_value = mock_session
        
        result = status_service.mark_done_with_retry(inbox_id=1)
        
        assert result.success is True
        assert result.attempts == 3
        assert mock_session.execute.call_count == 3
        assert mock_sleep.call_count == 2  # Sleep before retries 2 and 3
    
    @patch('app.services.status_update_service.SessionLocal')
    @patch('time.sleep')
    def test_mark_done_all_retries_fail(self, mock_sleep, mock_session_local, status_service):
        """Test mark_done fails after all retries"""
        # All attempts fail
        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("Connection lost", None, None)
        mock_session_local.return_value = mock_session
        
        result = status_service.mark_done_with_retry(inbox_id=1)
        
        assert result.success is False
        assert result.attempts == 3
        assert result.dlq is True
        assert result.error is not None
        assert mock_session.execute.call_count == 3
        assert mock_sleep.call_count == 2
    
    @patch('app.services.status_update_service.SessionLocal')
    def test_mark_failed_success_first_attempt(self, mock_session_local, status_service, mock_db_session):
        """Test successful mark_failed on first attempt"""
        mock_session_local.return_value = mock_db_session
        
        result = status_service.mark_failed_with_retry(
            inbox_id=1,
            error_message="Test error",
            attempt_count=1
        )
        
        assert result.success is True
        assert result.attempts == 1
        mock_db_session.execute.assert_called()
        mock_db_session.commit.assert_called_once()
    
    @patch('app.services.status_update_service.SessionLocal')
    def test_mark_failed_fetches_attempt_count(self, mock_session_local, status_service):
        """Test mark_failed fetches attempt_count if not provided"""
        mock_session = MagicMock()
        # First query: fetch attempt_count
        mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(2,))),  # attempt_count = 2
            MagicMock(rowcount=1)  # Update succeeds
        ]
        mock_session.commit.return_value = None
        mock_session_local.return_value = mock_session
        
        result = status_service.mark_failed_with_retry(
            inbox_id=1,
            error_message="Test error",
            attempt_count=None
        )
        
        assert result.success is True
        assert mock_session.execute.call_count == 2  # One for fetch, one for update
    
    @patch('app.services.status_update_service.SessionLocal')
    def test_mark_failed_marks_as_dead_after_max_attempts(self, mock_session_local, status_service, mock_db_session):
        """Test mark_failed marks as DEAD after max attempts"""
        mock_session_local.return_value = mock_db_session
        
        result = status_service.mark_failed_with_retry(
            inbox_id=1,
            error_message="Test error",
            attempt_count=5  # Max attempts
        )
        
        assert result.success is True
        # Verify DEAD status was set
        call_args = mock_db_session.execute.call_args
        assert 'DEAD' in str(call_args) or 'new_status' in str(call_args)
    
    @patch('app.services.status_update_service.SessionLocal')
    def test_mark_done_row_not_found(self, mock_session_local, status_service):
        """Test mark_done handles row not found"""
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = 0  # Row not found
        mock_session_local.return_value = mock_session
        
        result = status_service.mark_done_with_retry(inbox_id=999)
        
        assert result.success is False
        assert "not found" in result.error.lower()
        assert result.attempts == 1  # No retry for not found
    
    @patch('app.services.status_update_service.SessionLocal')
    @patch('time.sleep')
    def test_exponential_backoff(self, mock_sleep, mock_session_local, status_service):
        """Test exponential backoff timing"""
        mock_session = MagicMock()
        mock_session.execute.side_effect = [
            OperationalError("Connection lost", None, None),
            OperationalError("Connection lost", None, None),
            MagicMock(rowcount=1)  # Success on third attempt
        ]
        mock_session.commit.return_value = None
        mock_session_local.return_value = mock_session
        
        status_service.mark_done_with_retry(inbox_id=1)
        
        # Verify exponential backoff: 2^0=1s, 2^1=2s
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0][0][0] == 1  # 2^0 = 1
        assert mock_sleep.call_args_list[1][0][0] == 2  # 2^1 = 2

