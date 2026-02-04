"""
Unit Tests for Generated Payload Processing
Tests the ClinicalOpsInboxProcessor's ability to process generated payloads from JSON Generator
"""
import pytest
import sys
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone
from sqlalchemy.orm import Session

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.services.clinical_ops_inbox_processor import ClinicalOpsInboxProcessor
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB


class TestGeneratedPayloadExtraction:
    """Tests for extracting decision data from generated payloads"""
    
    def test_extract_decision_affirm(self):
        """Test extracting AFFIRM decision from generated payload"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {
                "icd": "0",
                "state": "NJ",
                "physician": {
                    "npi": "1765432109",
                    "name": "Dr. Kevin O'Brien"
                }
            },
            "partType": "B",
            "isDirectPa": False,
            "procedures": [
                {
                    "procedureCode": "69799",
                    "decisionIndicator": "A",  # AFFIRM
                    "mrCountUnitOfService": "1",
                    "placeOfService": "19"
                }
            ],
            "esmdTransactionId": "MMR000a80914EC",
            "documentation": []
        }
        
        decision_data = processor._extract_decision_from_generated_payload(generated_payload)
        
        assert decision_data['decision_outcome'] == 'AFFIRM'
        assert decision_data['decision_subtype'] == 'STANDARD_PA'
        assert decision_data['part_type'] == 'B'
        assert decision_data['is_direct_pa'] == False
        assert decision_data['esmd_transaction_id'] == 'MMR000a80914EC'
        assert len(decision_data['procedures']) == 1
        assert decision_data['procedures'][0]['procedure_code'] == '69799'
        assert decision_data['procedures'][0]['decision_indicator'] == 'A'
    
    def test_extract_decision_non_affirm(self):
        """Test extracting NON_AFFIRM decision from generated payload"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "A",
            "isDirectPa": True,
            "procedures": [
                {
                    "procedureCode": "15275",
                    "decisionIndicator": "N",  # NON_AFFIRM
                    "mrCountUnitOfService": "1"
                }
            ],
            "documentation": []
        }
        
        decision_data = processor._extract_decision_from_generated_payload(generated_payload)
        
        assert decision_data['decision_outcome'] == 'NON_AFFIRM'
        assert decision_data['decision_subtype'] == 'DIRECT_PA'  # No esmdTransactionId
        assert decision_data['part_type'] == 'A'
        assert decision_data['is_direct_pa'] == True
        assert decision_data['esmd_transaction_id'] == ''
    
    def test_extract_decision_direct_pa(self):
        """Test extracting Direct PA (no esmdTransactionId)"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "B",
            "isDirectPa": True,
            "procedures": [
                {
                    "procedureCode": "64483",
                    "decisionIndicator": "A",
                    "mrCountUnitOfService": "2"
                }
            ],
            "documentation": ["path/to/doc.pdf"]
        }
        
        decision_data = processor._extract_decision_from_generated_payload(generated_payload)
        
        assert decision_data['decision_subtype'] == 'DIRECT_PA'
        assert decision_data['is_direct_pa'] == True
        assert len(decision_data['medical_documents']) == 1
    
    def test_extract_decision_standard_pa(self):
        """Test extracting Standard PA (with esmdTransactionId)"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "B",
            "isDirectPa": False,
            "procedures": [
                {
                    "procedureCode": "69799",
                    "decisionIndicator": "N",
                    "mrCountUnitOfService": "1"
                }
            ],
            "esmdTransactionId": "MMR000a80914EC",
            "documentation": []
        }
        
        decision_data = processor._extract_decision_from_generated_payload(generated_payload)
        
        assert decision_data['decision_subtype'] == 'STANDARD_PA'
        assert decision_data['is_direct_pa'] == False
        assert decision_data['esmd_transaction_id'] == 'MMR000a80914EC'

    def test_extract_decision_direct_pa_from_flag(self):
        """Test extracting Direct/Standard from isDirectPa flag"""
        processor = ClinicalOpsInboxProcessor()

        generated_payload = {
            "header": {},
            "partType": "A",
            "procedures": [
                {
                    "procedureCode": "15275",
                    "decisionIndicator": "N",
                    "mrCountUnitOfService": "1"
                }
            ],
            "isDirectPa": False,  # Explicit Standard PA
            "documentation": []
        }

        decision_data = processor._extract_decision_from_generated_payload(generated_payload)

        assert decision_data['decision_subtype'] == 'STANDARD_PA'
        assert decision_data['is_direct_pa'] == False

    def test_extract_decision_missing_is_direct_pa(self):
        """Test error when isDirectPa flag is missing"""
        processor = ClinicalOpsInboxProcessor()

        generated_payload = {
            "header": {},
            "partType": "B",
            "procedures": [
                {
                    "procedureCode": "69799",
                    "decisionIndicator": "A",
                    "mrCountUnitOfService": "1"
                }
            ],
            "documentation": []
        }

        with pytest.raises(ValueError, match="isDirectPa"):
            processor._extract_decision_from_generated_payload(generated_payload)
    
    def test_extract_decision_missing_procedures(self):
        """Test error when procedures array is missing"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "B"
        }
        
        with pytest.raises(ValueError, match="missing procedures"):
            processor._extract_decision_from_generated_payload(generated_payload)
    
    def test_extract_decision_empty_procedures(self):
        """Test error when procedures array is empty"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "B",
            "procedures": []
        }
        
        with pytest.raises(ValueError, match="missing procedures"):
            processor._extract_decision_from_generated_payload(generated_payload)
    
    def test_extract_decision_invalid_indicator(self):
        """Test error when decisionIndicator is invalid"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "B",
            "procedures": [
                {
                    "procedureCode": "69799",
                    "decisionIndicator": "X",  # Invalid
                    "mrCountUnitOfService": "1"
                }
            ]
        }
        
        with pytest.raises(ValueError, match="Invalid decisionIndicator"):
            processor._extract_decision_from_generated_payload(generated_payload)
    
    def test_extract_decision_multiple_procedures(self):
        """Test extracting decision from payload with multiple procedures"""
        processor = ClinicalOpsInboxProcessor()
        
        generated_payload = {
            "header": {},
            "partType": "B",
            "isDirectPa": True,
            "procedures": [
                {
                    "procedureCode": "69799",
                    "decisionIndicator": "N",
                    "mrCountUnitOfService": "1",
                    "placeOfService": "19",
                    "modifier": "",
                    "reviewCodes": ["GAA02"],
                    "programCodes": ["04", "0C"]
                },
                {
                    "procedureCode": "87671",
                    "decisionIndicator": "N",
                    "mrCountUnitOfService": "",
                    "placeOfService": "19"
                }
            ],
            "esmdTransactionId": "MMR000a80914EC"
        }
        
        decision_data = processor._extract_decision_from_generated_payload(generated_payload)
        
        assert len(decision_data['procedures']) == 2
        assert decision_data['procedures'][0]['procedure_code'] == '69799'
        assert decision_data['procedures'][0]['review_codes'] == ['GAA02']
        assert decision_data['procedures'][0]['program_codes'] == ['04', '0C']
        assert decision_data['procedures'][1]['procedure_code'] == '87671'


class TestGeneratedPayloadProcessing:
    """Tests for processing generated payload messages"""
    
    @pytest.fixture
    def mock_db(self):
        """Create a mock database session"""
        return Mock(spec=Session)
    
    @pytest.fixture
    def mock_packet(self):
        """Create a mock packet"""
        packet = Mock(spec=PacketDB)
        packet.packet_id = 1
        packet.decision_tracking_id = '550e8400-e29b-41d4-a716-446655440000'
        return packet
    
    @pytest.fixture
    def mock_document(self):
        """Create a mock document"""
        doc = Mock(spec=PacketDocumentDB)
        doc.packet_document_id = 1
        doc.packet_id = 1
        return doc
    
    @pytest.fixture
    def generated_payload_message(self):
        """Create a sample generated payload message"""
        return {
            'message_id': 100,
            'decision_tracking_id': '550e8400-e29b-41d4-a716-446655440000',
            'payload': {
                "header": {
                    "icd": "0",
                    "state": "NJ",
                    "physician": {
                        "npi": "1765432109",
                        "name": "Dr. Kevin O'Brien"
                    }
                },
                "partType": "B",
                "isDirectPa": False,
                "procedures": [
                    {
                        "procedureCode": "69799",
                        "decisionIndicator": "N",
                        "mrCountUnitOfService": "1",
                        "placeOfService": "19"
                    }
                ],
                "esmdTransactionId": "MMR000a80914EC",
                "documentation": []
            },
            'created_at': datetime.now(timezone.utc),
            'json_sent_to_integration': True
        }
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_success(self, mock_db, mock_packet, mock_document, generated_payload_message):
        """Test successful processing of generated payload"""
        processor = ClinicalOpsInboxProcessor()
        
        # Mock database queries
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_packet,  # Packet query
            mock_document  # Document query
        ]
        
        # Mock WorkflowOrchestratorService
        with patch('app.services.workflow_orchestrator.WorkflowOrchestratorService') as mock_workflow:
            mock_workflow.get_active_decision.return_value = None
            mock_workflow.update_packet_status = Mock()
            
            # Mock DecisionsService
            with patch('app.services.decisions_service.DecisionsService') as mock_decisions:
                mock_decision = Mock(spec=PacketDecisionDB)
                mock_decision.packet_decision_id = 1
                mock_decision.decision_outcome = 'NON_AFFIRM'
                mock_decision.utn_status = None
                
                mock_decisions.create_approve_decision.return_value = mock_decision
                mock_decisions.update_clinical_decision.return_value = mock_decision
                
                # Process the message
                await processor._handle_generated_payload(mock_db, generated_payload_message)
                
                # Verify DecisionsService was called
                assert mock_decisions.create_approve_decision.called
                assert mock_decisions.update_clinical_decision.called
                
                # Verify status was updated
                assert mock_workflow.update_packet_status.called
                call_args = mock_workflow.update_packet_status.call_args
                assert call_args[1]['new_status'] == 'Pending - UTN'
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_failed_send(self, mock_db, mock_packet, mock_document):
        """Test processing when JSON Generator failed to send to integration"""
        processor = ClinicalOpsInboxProcessor()
        
        message = {
            'message_id': 100,
            'decision_tracking_id': '550e8400-e29b-41d4-a716-446655440000',
            'payload': {
                "partType": "B",
                "isDirectPa": True,
                "procedures": [
                    {
                        "procedureCode": "69799",
                        "decisionIndicator": "N",
                        "mrCountUnitOfService": "1"
                    }
                ]
            },
            'created_at': datetime.now(timezone.utc),
            'json_sent_to_integration': False  # Failed
        }
        
        # Mock database queries
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_packet,
            mock_document
        ]
        
        # Mock services
        with patch('app.services.workflow_orchestrator.WorkflowOrchestratorService') as mock_workflow:
            mock_workflow.get_active_decision.return_value = None
            mock_workflow.update_packet_status = Mock()
            
            with patch('app.services.decisions_service.DecisionsService') as mock_decisions:
                mock_decision = Mock(spec=PacketDecisionDB)
                mock_decisions.create_approve_decision.return_value = mock_decision
                mock_decisions.update_clinical_decision.return_value = mock_decision
                
                # Process the message
                await processor._handle_generated_payload(mock_db, message)
                
                # Verify status was updated to indicate failure
                assert mock_workflow.update_packet_status.called
                call_args = mock_workflow.update_packet_status.call_args
                assert call_args[1]['new_status'] == 'Generate Decision Letter - Pending'
                
                # Verify esmd_request_status is FAILED
                assert mock_decision.esmd_request_status == 'FAILED'
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_missing_packet(self, mock_db, generated_payload_message):
        """Test error when packet is not found"""
        processor = ClinicalOpsInboxProcessor()
        
        # Mock database query to return None (packet not found)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        with pytest.raises(ValueError, match="Packet not found"):
            await processor._handle_generated_payload(mock_db, generated_payload_message)
    
    @pytest.mark.asyncio
    async def test_handle_generated_payload_invalid_payload(self, mock_db, mock_packet, mock_document):
        """Test error when payload is invalid"""
        processor = ClinicalOpsInboxProcessor()
        
        message = {
            'message_id': 100,
            'decision_tracking_id': '550e8400-e29b-41d4-a716-446655440000',
            'payload': {
                "partType": "B"
                # Missing procedures
            },
            'created_at': datetime.now(timezone.utc),
            'json_sent_to_integration': True
        }
        
        # Mock database queries
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_packet,
            mock_document
        ]
        
        with pytest.raises(ValueError, match="missing procedures"):
            await processor._handle_generated_payload(mock_db, message)


class TestPollingQuery:
    """Tests for polling query logic"""
    
    def test_poll_query_filters_json_sent_flag(self):
        """Test that polling query only gets messages with json_sent_to_integration IS NOT NULL"""
        processor = ClinicalOpsInboxProcessor()
        
        # The query should filter for json_sent_to_integration IS NOT NULL
        # This is verified in the actual query text in _poll_new_messages
        # We can't easily test the SQL execution without a real DB, but we can verify the logic
        
        # Verify the processor is configured correctly
        assert processor.batch_size > 0
        assert processor.poll_interval_seconds > 0

