"""
Channel Processing Strategy Pattern
Defines channel-specific processing logic for multi-channel support
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from app.models.channel_type import ChannelType
from app.services.part_classifier import PartClassifier

logger = logging.getLogger(__name__)


class ChannelProcessingStrategy(ABC):
    """
    Abstract base class for channel-specific processing strategies
    
    Each channel type (ESMD, Genzeon Fax, Genzeon Portal) has different requirements:
    - ESMD: Full OCR workflow
    - Genzeon Fax: Full OCR workflow (same as ESMD)
    - Genzeon Portal: Skip OCR, extract from payload.ocr
    """
    
    @abstractmethod
    def should_run_ocr(self) -> bool:
        """
        Determine if OCR should be run for this channel
        
        Returns:
            True if OCR should be run, False if fields should be extracted from payload
        """
        pass
    
    @abstractmethod
    def extract_fields_from_payload(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Dict[str, Any]:
        """
        Extract OCR fields from payload (for channels that skip OCR)
        
        Args:
            payload: Full payload from integration.send_serviceops
            split_result: SplitResult from document splitting (for page context)
            
        Returns:
            Standard extracted_fields format matching OCR output:
            {
                "fields": {...},
                "coversheet_type": "...",
                "doc_type": "...",
                "overall_document_confidence": 0.0-1.0,
                "duration_ms": 0,
                "page_number": 1,
                "raw": {...},
                "source": "PAYLOAD_INITIAL"
            }
            
        Raises:
            ValueError: If payload structure is invalid or missing required fields
        """
        pass
    
    @abstractmethod
    def get_coversheet_page_number(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Optional[int]:
        """
        Get coversheet page number from payload or default
        
        Args:
            payload: Full payload from integration.send_serviceops
            split_result: SplitResult from document splitting
            
        Returns:
            Page number (1-indexed) of coversheet, or None if not found/not applicable
        """
        pass
    
    @abstractmethod
    def get_part_type(self, payload: Dict[str, Any]) -> str:
        """
        Get Part type (PART_A, PART_B, UNKNOWN) from payload or default
        
        Args:
            payload: Full payload from integration.send_serviceops
            
        Returns:
            Part type: "PART_A", "PART_B", or "UNKNOWN"
        """
        pass


class ESMDProcessingStrategy(ChannelProcessingStrategy):
    """
    ESMD (channel_type_id = 3) processing strategy
    Uses full OCR workflow - no changes from existing behavior
    """
    
    def should_run_ocr(self) -> bool:
        """ESMD always runs OCR"""
        return True
    
    def extract_fields_from_payload(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Dict[str, Any]:
        """
        ESMD does not extract from payload - OCR is used instead
        This method should not be called for ESMD, but if it is, raise an error
        """
        raise NotImplementedError(
            "ESMDProcessingStrategy does not extract fields from payload. "
            "Use OCR workflow instead."
        )
    
    def get_coversheet_page_number(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Optional[int]:
        """
        ESMD detects coversheet via OCR, not from payload
        This method should not be called for ESMD, but if it is, return default
        """
        logger.warning(
            "get_coversheet_page_number called for ESMD - coversheet is detected via OCR, not payload"
        )
        return 1  # Default fallback (OCR will set actual value)
    
    def get_part_type(self, payload: Dict[str, Any]) -> str:
        """
        ESMD classifies Part A/B via OCR, not from payload
        This method should not be called for ESMD, but if it is, return default
        """
        logger.warning(
            "get_part_type called for ESMD - part type is classified via OCR, not payload"
        )
        return "UNKNOWN"  # Default fallback


class GenzeonFaxProcessingStrategy(ChannelProcessingStrategy):
    """
    Genzeon Fax (channel_type_id = 2) processing strategy
    Uses full OCR workflow - same as ESMD
    """
    
    def should_run_ocr(self) -> bool:
        """Genzeon Fax always runs OCR"""
        return True
    
    def extract_fields_from_payload(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Dict[str, Any]:
        """
        Genzeon Fax does not extract from payload - OCR is used instead
        This method should not be called for Genzeon Fax, but if it is, raise an error
        """
        raise NotImplementedError(
            "GenzeonFaxProcessingStrategy does not extract fields from payload. "
            "Use OCR workflow instead."
        )
    
    def get_coversheet_page_number(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Optional[int]:
        """
        Genzeon Fax detects coversheet via OCR, not from payload
        This method should not be called for Genzeon Fax, but if it is, return default
        """
        logger.warning(
            "get_coversheet_page_number called for Genzeon Fax - coversheet is detected via OCR, not payload"
        )
        return 1  # Default fallback (OCR will set actual value)
    
    def get_part_type(self, payload: Dict[str, Any]) -> str:
        """
        Genzeon Fax classifies Part A/B via OCR, not from payload
        This method should not be called for Genzeon Fax, but if it is, return default
        """
        logger.warning(
            "get_part_type called for Genzeon Fax - part type is classified via OCR, not payload"
        )
        return "UNKNOWN"  # Default fallback


class GenzeonPortalProcessingStrategy(ChannelProcessingStrategy):
    """
    Genzeon Portal (channel_type_id = 1) processing strategy
    Skips OCR and extracts fields directly from payload.ocr
    """
    
    def should_run_ocr(self) -> bool:
        """Genzeon Portal skips OCR"""
        return False
    
    def extract_fields_from_payload(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Dict[str, Any]:
        """
        Extract OCR fields from payload.ocr and map to standard extracted_fields format.
        
        Expected payload structure:
        {
            "ocr": {
                "fields": {
                    "Field Name": {
                        "value": "...",
                        "confidence": 1,  # int, needs conversion to float
                        "field_type": "DocumentFieldType.STRING"  # needs normalization
                    },
                    ...
                },
                "doc_type": "coversheet-extraction",
                "model_id": "coversheet-extraction",
                "coversheet_type": "...",
                "overall_document_confidence": 0.999
            }
        }
        
        Returns standard format matching OCR output.
        """
        ocr_data = payload.get('ocr')
        if not ocr_data or not isinstance(ocr_data, dict):
            raise ValueError(
                "Genzeon Portal payload missing 'ocr' object or it's not a dictionary. "
                f"Payload keys: {list(payload.keys())}"
            )
        
        ocr_fields_raw = ocr_data.get('fields', {})
        if not ocr_fields_raw or not isinstance(ocr_fields_raw, dict):
            raise ValueError(
                "Genzeon Portal payload missing 'ocr.fields' object or it's not a dictionary. "
                f"OCR data keys: {list(ocr_data.keys())}"
            )
        
        # Build initial structure with raw fields (before normalization)
        initial_fields = {}
        for field_name, field_data in ocr_fields_raw.items():
            if isinstance(field_data, dict):
                initial_fields[field_name] = field_data
            else:
                initial_fields[field_name] = {
                    'value': str(field_data) if field_data else '',
                    'confidence': 1.0,
                    'field_type': 'STRING'
                }
        
        # Extract metadata from payload.ocr
        coversheet_type = ocr_data.get('coversheet_type', '')
        doc_type = ocr_data.get('doc_type', 'coversheet-extraction')
        overall_document_confidence = float(ocr_data.get('overall_document_confidence', 0.0))
        
        # Get coversheet page number (default to 1)
        coversheet_page_number = self.get_coversheet_page_number(payload, split_result)
        
        # Build initial structure (will be normalized)
        initial_payload = {
            'fields': initial_fields,
            'coversheet_type': coversheet_type,
            'doc_type': doc_type,
            'overall_document_confidence': overall_document_confidence,
            'duration_ms': 0,  # No OCR processing time
            'page_number': coversheet_page_number,
            'raw': {
                'source': 'payload',
                'ocr': ocr_data  # Will be cleaned by normalizer
            },
            'source': 'PAYLOAD_INITIAL'  # Mark as from payload, not OCR
        }
        
        # Normalize the entire structure (deduplicates, normalizes names, cleans raw)
        from app.utils.field_normalizer import FieldNormalizer
        normalized_payload = FieldNormalizer.normalize_extracted_fields(initial_payload, source='PAYLOAD_INITIAL')
        
        return normalized_payload
    
    def get_coversheet_page_number(
        self,
        payload: Dict[str, Any],
        split_result: Any
    ) -> Optional[int]:
        """
        Portal has no physical coversheet - data is entered via UI.
        Always return None (no coversheet page).
        
        Args:
            payload: Full payload from integration.send_serviceops
            split_result: SplitResult from document splitting (for validation)
            
        Returns:
            None (Portal has no coversheet)
        """
        # Portal has no coversheet - always return None
        return None
        coversheet_page = (
            ocr_data.get('coversheet_page_number') or
            ocr_data.get('coversheetPageNumber') or
            ocr_data.get('coversheet_page')
        )
        
        if coversheet_page is not None:
            try:
                page_num = int(coversheet_page)
                if page_num >= 1:
                    # Validate against split_result if available
                    if split_result and hasattr(split_result, 'pages'):
                        max_pages = len(split_result.pages)
                        if page_num > max_pages:
                            logger.warning(
                                f"coversheet_page_number={page_num} exceeds max pages={max_pages}, "
                                "defaulting to 1"
                            )
                            return 1
                    return page_num
            except (ValueError, TypeError):
                logger.warning(
                    f"Invalid coversheet_page_number value: {coversheet_page}, defaulting to 1"
                )
        
        # Default to page 1
        return 1
    
    def get_part_type(self, payload: Dict[str, Any]) -> str:
        """
        Get Part type from payload.ocr.part_type or classify using PartClassifier
        
        Args:
            payload: Full payload from integration.send_serviceops
            
        Returns:
            Part type: "PART_A", "PART_B", or "UNKNOWN"
        """
        ocr_data = payload.get('ocr', {})
        if not isinstance(ocr_data, dict):
            return 'UNKNOWN'
        
        # Step 1: Try direct part_type field first (if it exists)
        part_type = (
            ocr_data.get('part_type') or
            ocr_data.get('partType') or
            ocr_data.get('part_type_classification')
        )
        
        if part_type and isinstance(part_type, str):
            part_type_upper = part_type.upper().strip()
            if part_type_upper in ['PART_A', 'PART_B', 'UNKNOWN']:
                logger.debug(f"Portal: Found part_type in payload.ocr.part_type: {part_type_upper}")
                return part_type_upper
        
        # Step 2: Fallback to PartClassifier using coversheet_type and fields
        # Build OCR result structure from payload.ocr for PartClassifier
        ocr_result = {
            'coversheet_type': ocr_data.get('coversheet_type', ''),
            'fields': ocr_data.get('fields', {})
        }
        
        # Use PartClassifier to classify based on coversheet_type (e.g., "Medicare Part B")
        try:
            classifier = PartClassifier()
            classified_part_type = classifier.classify_part_type(ocr_result)
            logger.info(
                f"Portal: Classified part_type using PartClassifier: {classified_part_type} "
                f"(from coversheet_type: {ocr_result.get('coversheet_type', '')[:100]})"
            )
            return classified_part_type
        except Exception as e:
            logger.warning(
                f"Portal: PartClassifier failed, defaulting to UNKNOWN. Error: {e}"
            )
            return 'UNKNOWN'


def get_channel_strategy(channel_type_id: Optional[int]) -> ChannelProcessingStrategy:
    """
    Factory function to get the appropriate channel processing strategy
    
    Args:
        channel_type_id: Channel type ID (1=Portal, 2=Fax, 3=ESMD), None or empty defaults to ESMD (3)
        
    Returns:
        ChannelProcessingStrategy instance
        
    Defaults to ESMDProcessingStrategy (3) if channel_type_id is None, empty, or unknown
    """
    # Normalize: treat None, 0, or empty as ESMD (3)
    if channel_type_id is None or channel_type_id == 0:
        logger.debug("channel_type_id is None or 0, defaulting to ESMD (3)")
        return ESMDProcessingStrategy()
    
    if channel_type_id == ChannelType.GENZEON_PORTAL:
        return GenzeonPortalProcessingStrategy()
    elif channel_type_id == ChannelType.GENZEON_FAX:
        return GenzeonFaxProcessingStrategy()
    elif channel_type_id == ChannelType.ESMD:
        return ESMDProcessingStrategy()
    else:
        # Unknown channel_type_id - default to ESMD
        logger.warning(
            f"Unknown channel_type_id={channel_type_id}, defaulting to ESMDProcessingStrategy (3)"
        )
        return ESMDProcessingStrategy()

