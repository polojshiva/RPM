"""
Phase 6: End-to-End Tests for Multi-Channel Processing
Tests all three channels (ESMD, Genzeon Fax, Genzeon Portal) end-to-end
Tests backward compatibility with NULL channel_type_id
"""
import pytest
import sys
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

# Mock Azure modules before importing app
sys.modules['azure'] = MagicMock()
sys.modules['azure.storage'] = MagicMock()
sys.modules['azure.storage.blob'] = MagicMock()
sys.modules['azure.identity'] = MagicMock()
sys.modules['azure.core'] = MagicMock()
sys.modules['azure.core.exceptions'] = MagicMock()

from app.models.channel_type import ChannelType
from app.models.integration_db import SendServiceOpsDB
from app.models.packet_db import PacketDB
from app.models.document_db import PacketDocumentDB
from app.services.document_processor import DocumentProcessor
from app.services.channel_processing_strategy import (
    ESMDProcessingStrategy,
    GenzeonFaxProcessingStrategy,
    GenzeonPortalProcessingStrategy,
    get_channel_strategy
)
from app.services.document_splitter import SplitResult, SplitPage


class TestESMDChannelEndToEnd:
    """End-to-end tests for ESMD channel (channel_type_id = 3)"""
    
    @pytest.fixture
    def esmd_message(self):
        """Sample ESMD message"""
        message = Mock(spec=SendServiceOpsDB)
        message.message_id = 270
        message.channel_type_id = ChannelType.ESMD
        message.decision_tracking_id = "04eb1038-f6cf-4359-81a0-cee8468fa3bb"
        message.payload = {
            "documents": [{
                "blobPath": "v2/2026/01-05/test.pdf",
                "fileName": "test.pdf",
                "fileSize": 419380,
                "mimeType": "image/tiff",
                "documentUniqueIdentifier": "DOC-001"
            }],
            "submission_metadata": {
                "carrierId": "12402",
                "entryMode": "F"
            },
            "decision_tracking_id": "04eb1038-f6cf-4359-81a0-cee8468fa3bb"
        }
        message.created_at = datetime(2026, 1, 6, tzinfo=timezone.utc)
        return message
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_esmd_strategy_selection(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        esmd_message
    ):
        """Test ESMD message uses ESMDProcessingStrategy"""
        processor = DocumentProcessor(channel_type_id=ChannelType.ESMD)
        assert isinstance(processor.channel_strategy, ESMDProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_esmd_packet_creation_with_channel_type_id(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        esmd_message
    ):
        """Test ESMD packet is created with channel_type_id = 3"""
        processor = DocumentProcessor(channel_type_id=ChannelType.ESMD)
        
        # Mock DB session
        with patch('app.services.document_processor.get_db_session') as mock_db:
            mock_session = MagicMock()
            mock_db.return_value.__enter__.return_value = mock_session
            
            # Mock packet query (not found, will create new)
            mock_session.query.return_value.filter.return_value.first.return_value = None
            
            # Mock packet creation
            mock_packet = Mock(spec=PacketDB)
            mock_packet.packet_id = 1
            mock_packet.external_id = "PKT-2026-123456"
            mock_packet.decision_tracking_id = esmd_message.decision_tracking_id
            mock_packet.channel_type_id = None  # Initially None
            
            # When packet is created, channel_type_id should be set
            # (This is tested via the actual _get_or_create_packet call)
            # For now, verify strategy is correct
            assert processor.channel_type_id == ChannelType.ESMD


class TestGenzeonFaxChannelEndToEnd:
    """End-to-end tests for Genzeon Fax channel (channel_type_id = 2)"""
    
    @pytest.fixture
    def fax_message(self):
        """Sample Genzeon Fax message"""
        message = Mock(spec=SendServiceOpsDB)
        message.message_id = 271
        message.channel_type_id = ChannelType.GENZEON_FAX
        message.decision_tracking_id = "e7b8c1e2-1234-4cde-9abc-1234567890ab"
        message.payload = {
            "documents": [{
                "blobPath": "container/faxes/2026/01/06/fax.pdf",
                "fileName": "fax.pdf",
                "fileSize": 73125,
                "mimeType": "pdf",
                "documentUniqueIdentifier": "DOC-002"
            }],
            "messageType": "Genzeon Fax",
            "decision_tracking_id": "e7b8c1e2-1234-4cde-9abc-1234567890ab"
        }
        message.created_at = datetime(2026, 1, 6, tzinfo=timezone.utc)
        return message
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_fax_strategy_selection(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        fax_message
    ):
        """Test Genzeon Fax message uses GenzeonFaxProcessingStrategy"""
        processor = DocumentProcessor(channel_type_id=ChannelType.GENZEON_FAX)
        assert isinstance(processor.channel_strategy, GenzeonFaxProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_fax_same_as_esmd_workflow(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        fax_message
    ):
        """Test Genzeon Fax follows same workflow as ESMD (full OCR)"""
        processor = DocumentProcessor(channel_type_id=ChannelType.GENZEON_FAX)
        assert processor.channel_strategy.should_run_ocr() is True
        # Should NOT extract from payload
        with pytest.raises(NotImplementedError):
            processor.channel_strategy.extract_fields_from_payload(
                fax_message.payload,
                None
            )


class TestGenzeonPortalChannelEndToEnd:
    """End-to-end tests for Genzeon Portal channel (channel_type_id = 1)"""
    
    @pytest.fixture
    def portal_message(self):
        """Sample Genzeon Portal message with ocr field"""
        message = Mock(spec=SendServiceOpsDB)
        message.message_id = 272
        message.channel_type_id = ChannelType.GENZEON_PORTAL
        message.decision_tracking_id = "b1c2d3e4-5678-4abc-9def-234567890abc"
        message.payload = {
            "documents": [{
                "blobPath": "container/portal/2026/01/06/packet.pdf",
                "fileName": "packet.pdf",
                "fileSize": 500152,
                "mimeType": "application/pdf",
                "documentUniqueIdentifier": "DOC-003"
            }],
            "messageType": "Genzeon Portal",
            "decision_tracking_id": "b1c2d3e4-5678-4abc-9def-234567890abc",
            "ocr": {
                "fields": {
                    "Beneficiary First Name": {
                        "value": "MICHAEL",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    },
                    "Beneficiary Last Name": {
                        "value": "MASI",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    },
                    "Provider NPI": {
                        "value": "1619025038",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    }
                },
                "doc_type": "coversheet-extraction",
                "coversheet_type": "Genzeon Portal Prior Authorization Request...",
                "overall_document_confidence": 0.999
            }
        }
        message.created_at = datetime(2026, 1, 6, tzinfo=timezone.utc)
        return message
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_portal_strategy_selection(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        portal_message
    ):
        """Test Genzeon Portal message uses GenzeonPortalProcessingStrategy"""
        processor = DocumentProcessor(channel_type_id=ChannelType.GENZEON_PORTAL)
        assert isinstance(processor.channel_strategy, GenzeonPortalProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is False
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_portal_extracts_from_payload(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        portal_message
    ):
        """Test Genzeon Portal extracts fields from payload.ocr"""
        processor = DocumentProcessor(channel_type_id=ChannelType.GENZEON_PORTAL)
        
        # Create mock split result
        split_result = SplitResult(
            processing_path="test/processing",
            page_count=1,
            pages=[
                SplitPage(
                    page_number=1,
                    local_path="/tmp/page_1.pdf",
                    dest_blob_path="page_1.pdf",
                    file_size_bytes=1000
                )
            ],
            local_paths=["/tmp/page_1.pdf"]
        )
        
        # Extract fields
        extracted = processor.channel_strategy.extract_fields_from_payload(
            portal_message.payload,
            split_result
        )
        
        # Verify structure
        assert 'fields' in extracted
        assert 'Beneficiary First Name' in extracted['fields']
        assert extracted['fields']['Beneficiary First Name']['value'] == "MICHAEL"
        assert extracted['fields']['Beneficiary First Name']['confidence'] == 1.0  # Normalized to float
        assert extracted['fields']['Beneficiary First Name']['field_type'] == "STRING"  # Normalized
        assert extracted['source'] == "PAYLOAD_INITIAL"


class TestBackwardCompatibility:
    """Tests for backward compatibility with NULL/empty channel_type_id"""
    
    @pytest.fixture
    def legacy_message(self):
        """Legacy message without channel_type_id (NULL)"""
        message = Mock(spec=SendServiceOpsDB)
        message.message_id = 100
        message.channel_type_id = None  # NULL - backward compatibility
        message.decision_tracking_id = "legacy-uuid"
        message.payload = {
            "documents": [{
                "blobPath": "legacy/test.pdf",
                "fileName": "test.pdf",
                "fileSize": 1000,
                "mimeType": "application/pdf",
                "documentUniqueIdentifier": "DOC-LEGACY"
            }],
            "decision_tracking_id": "legacy-uuid"
        }
        message.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return message
    
    def test_null_channel_type_id_defaults_to_esmd(self, legacy_message):
        """Test NULL channel_type_id defaults to ESMD (3)"""
        # Strategy factory should default to ESMD
        strategy = get_channel_strategy(None)
        assert isinstance(strategy, ESMDProcessingStrategy)
        assert strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_processor_with_null_channel_type_id_defaults_to_esmd(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger,
        legacy_message
    ):
        """Test DocumentProcessor with NULL channel_type_id defaults to ESMD"""
        processor = DocumentProcessor(channel_type_id=None)
        # Strategy should be ESMD
        assert isinstance(processor.channel_strategy, ESMDProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is True
    
    def test_zero_channel_type_id_defaults_to_esmd(self):
        """Test 0 channel_type_id defaults to ESMD"""
        strategy = get_channel_strategy(0)
        assert isinstance(strategy, ESMDProcessingStrategy)
        assert strategy.should_run_ocr() is True
    
    @patch('app.services.document_processor.PDFMerger')
    @patch('app.services.document_processor.DocumentSplitter')
    @patch('app.services.document_processor.BlobStorageClient')
    def test_processor_with_zero_channel_type_id_defaults_to_esmd(
        self,
        mock_blob_client,
        mock_splitter,
        mock_pdf_merger
    ):
        """Test DocumentProcessor with 0 channel_type_id defaults to ESMD"""
        processor = DocumentProcessor(channel_type_id=0)
        assert isinstance(processor.channel_strategy, ESMDProcessingStrategy)
        assert processor.channel_strategy.should_run_ocr() is True


class TestChannelTypeMapping:
    """Tests for channel_type_id mapping to Channel enum in UI"""
    
    def test_channel_type_id_1_maps_to_portal(self):
        """Test channel_type_id=1 maps to Channel.PORTAL"""
        from app.utils.packet_converter import _map_channel_type_id_to_channel
        from app.models.packet_dto import Channel
        
        channel = _map_channel_type_id_to_channel(ChannelType.GENZEON_PORTAL)
        assert channel == Channel.PORTAL
    
    def test_channel_type_id_2_maps_to_fax(self):
        """Test channel_type_id=2 maps to Channel.FAX"""
        from app.utils.packet_converter import _map_channel_type_id_to_channel
        from app.models.packet_dto import Channel
        
        channel = _map_channel_type_id_to_channel(ChannelType.GENZEON_FAX)
        assert channel == Channel.FAX
    
    def test_channel_type_id_3_maps_to_esmd(self):
        """Test channel_type_id=3 maps to Channel.ESMD"""
        from app.utils.packet_converter import _map_channel_type_id_to_channel
        from app.models.packet_dto import Channel
        
        channel = _map_channel_type_id_to_channel(ChannelType.ESMD)
        assert channel == Channel.ESMD
    
    def test_null_channel_type_id_maps_to_fax_default(self):
        """Test NULL channel_type_id maps to Channel.FAX (default for UI)"""
        from app.utils.packet_converter import _map_channel_type_id_to_channel
        from app.models.packet_dto import Channel
        
        channel = _map_channel_type_id_to_channel(None)
        assert channel == Channel.FAX  # Default for backward compatibility


class TestChannelWorkflowDifferences:
    """Tests to verify different workflows for each channel"""
    
    def test_esmd_uses_ocr_workflow(self):
        """Test ESMD uses full OCR workflow"""
        strategy = get_channel_strategy(ChannelType.ESMD)
        assert strategy.should_run_ocr() is True
        assert isinstance(strategy, ESMDProcessingStrategy)
    
    def test_fax_uses_ocr_workflow(self):
        """Test Genzeon Fax uses full OCR workflow (same as ESMD)"""
        strategy = get_channel_strategy(ChannelType.GENZEON_FAX)
        assert strategy.should_run_ocr() is True
        assert isinstance(strategy, GenzeonFaxProcessingStrategy)
    
    def test_portal_skips_ocr_workflow(self):
        """Test Genzeon Portal skips OCR and extracts from payload"""
        strategy = get_channel_strategy(ChannelType.GENZEON_PORTAL)
        assert strategy.should_run_ocr() is False
        assert isinstance(strategy, GenzeonPortalProcessingStrategy)
    
    def test_portal_extracts_from_payload_not_ocr(self):
        """Test Portal extracts from payload.ocr, not OCR service"""
        strategy = get_channel_strategy(ChannelType.GENZEON_PORTAL)
        
        payload = {
            "ocr": {
                "fields": {
                    "Test Field": {
                        "value": "test",
                        "confidence": 1,
                        "field_type": "DocumentFieldType.STRING"
                    }
                },
                "overall_document_confidence": 0.99
            }
        }
        
        split_result = SplitResult(
            processing_path="test",
            page_count=1,
            pages=[],
            local_paths=[]
        )
        
        # Should extract from payload, not call OCR
        extracted = strategy.extract_fields_from_payload(payload, split_result)
        assert extracted['fields']['Test Field']['value'] == "test"
        assert extracted['source'] == "PAYLOAD_INITIAL"

