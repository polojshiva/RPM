"""
Load Tests for UTN Workflow
Tests system behavior under load and concurrent operations
"""
import pytest
import sys
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.utn_handlers import UtnSuccessHandler, UtnFailHandler
from app.services.esmd_payload_generator import EsmdPayloadGenerator


class TestConcurrentLoad:
    """Test concurrent processing under load"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock()
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        return db
    
    def test_concurrent_utn_success_processing(self, mock_db):
        """Test processing multiple UTN_SUCCESS messages concurrently"""
        # Create multiple packets and decisions
        packets = []
        decisions = []
        for i in range(10):
            packet = Mock()
            packet.packet_id = 100 + i
            packet.decision_tracking_id = f"550e8400-e29b-41d4-a716-44665544000{i}"
            packets.append(packet)
            
            decision = Mock()
            decision.packet_id = 100 + i
            decision.utn = None
            decision.utn_status = 'NONE'
            decisions.append(decision)
        
        # Mock query to return packets and decisions in order
        query_results = []
        for packet, decision in zip(packets, decisions):
            query_results.extend([packet, decision])
        
        mock_db.query.return_value.filter.return_value.first.side_effect = query_results
        
        # Process concurrently
        def process_utn(i):
            payload = {
                "message_type": "UTN",
                "unique_tracking_number": f"JLB8626008003{i}",
                "decision_tracking_id": f"550e8400-e29b-41d4-a716-44665544000{i}"
            }
            message = {
                'message_id': i,
                'decision_tracking_id': f"550e8400-e29b-41d4-a716-44665544000{i}",
                'payload': payload
            }
            import asyncio
            asyncio.run(UtnSuccessHandler.handle(mock_db, message))
            return i
        
        # Use ThreadPoolExecutor to simulate concurrent processing
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_utn, i) for i in range(10)]
            results = [f.result() for f in as_completed(futures)]
        
        # Verify all processed
        assert len(results) == 10
        assert all(i in results for i in range(10))
    
    def test_concurrent_payload_generation(self, mock_db):
        """Test generating multiple ESMD payloads concurrently"""
        generator = EsmdPayloadGenerator(mock_db)
        
        # Mock document
        document = Mock()
        document.extracted_fields = {"fields": {}}
        mock_db.query.return_value.filter.return_value.first.return_value = document
        
        # Create multiple packets and decisions
        packets = []
        decisions = []
        for i in range(20):
            packet = Mock()
            packet.packet_id = 200 + i
            packet.beneficiary_name = f"Patient {i}"
            packet.beneficiary_mbi = f"1EG4TE5MK7{i}"
            packet.provider_name = f"Clinic {i}"
            packet.provider_npi = f"123456789{i}"
            packet.submission_type = "Expedited"
            packets.append(packet)
            
            decision = Mock()
            decision.decision_outcome = "AFFIRM"
            decision.decision_subtype = "DIRECT_PA"
            decision.part_type = "B"
            decisions.append(decision)
        
        # Generate payloads concurrently
        def generate_payload(i):
            return generator.generate_payload(
                packet=packets[i],
                packet_decision=decisions[i],
                procedures=[],
                medical_docs=None
            )
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(generate_payload, i) for i in range(20)]
            payloads = [f.result() for f in as_completed(futures)]
        
        # Verify all payloads generated
        assert len(payloads) == 20
        assert all('header' in p for p in payloads)
        assert all('uniqueId' in p for p in payloads)


class TestRetryAndBackoff:
    """Test retry logic and backoff behavior"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock()
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        return db
    
    def test_retry_on_transient_db_error(self, mock_db):
        """Test retry behavior on transient DB errors"""
        from sqlalchemy.exc import OperationalError
        
        packet = Mock()
        packet.packet_id = 123
        decision = Mock()
        decision.packet_id = 123
        decision.utn = None
        
        # Mock query to return packet and decision
        def query_side_effect(*args, **kwargs):
            query_mock = Mock()
            filter_mock = Mock()
            if not hasattr(query_side_effect, 'call_count'):
                query_side_effect.call_count = 0
            query_side_effect.call_count += 1
            if query_side_effect.call_count % 2 == 1:
                filter_mock.first.return_value = packet
            else:
                filter_mock.first.return_value = decision
            query_mock.filter.return_value = filter_mock
            return query_mock
        
        mock_db.query.side_effect = query_side_effect
        
        # Simulate transient error on flush (handler uses flush, not commit)
        call_count = [0]
        def flush_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise OperationalError("connection lost", None, None)
            return None
        
        mock_db.flush.side_effect = flush_side_effect
        
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
        
        # First call should fail
        query_side_effect.call_count = 0
        import asyncio
        with pytest.raises(OperationalError):
            asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        
        # Note: Handler doesn't call rollback explicitly - it's handled by the caller/inbox processor
        # The exception propagates up for the caller to handle
        
        # Second call should succeed (simulate retry)
        query_side_effect.call_count = 0
        mock_db.flush.side_effect = None
        UtnSuccessHandler.handle(mock_db, message)
        
        # Verify success
        assert decision.utn == "JLB86260080030"


class TestIdempotencyUnderLoad:
    """Test idempotency guarantees under concurrent load"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        db = Mock()
        db.query = Mock()
        db.add = Mock()
        db.commit = Mock()
        return db
    
    def test_duplicate_messages_idempotent(self, mock_db):
        """Test that duplicate messages processed concurrently are idempotent"""
        packet = Mock()
        packet.packet_id = 123
        decision = Mock()
        decision.packet_id = 123
        decision.utn = None
        decision.utn_status = 'NONE'
        
        # Same packet/decision for all calls
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            packet, decision
        ] * 10  # 10 duplicate calls
        
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
        
        # Process same message 10 times concurrently
        def process_duplicate():
            import asyncio
            asyncio.run(UtnSuccessHandler.handle(mock_db, message))
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_duplicate) for _ in range(10)]
            [f.result() for f in as_completed(futures)]
        
        # Verify idempotency: all calls should result in same state
        assert decision.utn == "JLB86260080030"
        assert decision.utn_status == 'SUCCESS'
        # Should not create duplicate records or cause errors

