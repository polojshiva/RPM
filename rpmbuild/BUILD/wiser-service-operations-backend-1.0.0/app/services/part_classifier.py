"""
Part Classifier
Classifies Medicare Part A vs Part B based on coversheet_type or title field
"""
from typing import Dict, Any
from logging import getLogger

logger = getLogger(__name__)


class PartClassifier:
    """
    Classifies Medicare Part type (A or B) based on coversheet_type or title field
    
    Uses the coversheet_type string (or fields.title.value as fallback) to determine
    if a coversheet is Part A or Part B by checking for "medicare part a" or
    "medicare part b" in the normalized text.
    """
    
    def classify_part_type(self, ocr_result: Dict[str, Any]) -> str:
        """
        Classify Part A vs Part B based on coversheet_type or title field
        
        Args:
            ocr_result: OCR result dictionary with 'coversheet_type' or 'fields.title.value'
                Expected structure:
                {
                    'coversheet_type': 'Prior Authorization Request ... Medicare Part B ...',
                    'fields': {
                        'title': {
                            'value': '...',
                            'confidence': 0.96,
                            'field_type': 'STRING'
                        }
                    }
                }
        
        Returns:
            "PART_A", "PART_B", or "UNKNOWN"
        """
        # Get candidate string (coversheet_type first, then title)
        candidate = ocr_result.get('coversheet_type', '')
        source = 'coversheet_type'
        
        if not candidate:
            # Fallback to fields.title.value
            fields = ocr_result.get('fields', {})
            if isinstance(fields, dict):
                title_field = fields.get('title', {})
                if isinstance(title_field, dict):
                    candidate = title_field.get('value', '')
                    source = 'fields.title.value'
                else:
                    candidate = str(title_field) if title_field else ''
                    source = 'fields.title.value'
        
        if not candidate or not candidate.strip():
            logger.warning("No coversheet_type or title found, returning UNKNOWN")
            return "UNKNOWN"
        
        # Normalize: lowercase, collapse whitespace
        normalized = ' '.join(candidate.lower().split())
        
        # Check for Part A/B (Part A takes precedence if both found)
        has_part_a = 'medicare part a' in normalized
        has_part_b = 'medicare part b' in normalized
        
        if has_part_a and has_part_b:
            # Both found - Part A takes precedence
            logger.warning(
                f"Both 'medicare part a' and 'medicare part b' found in {source}, "
                f"preferring PART_A. Text: {candidate[:100]}"
            )
            logger.info(f"Classified as PART_A from {source}: {candidate[:100]}")
            return "PART_A"
        elif has_part_a:
            logger.info(f"Classified as PART_A from {source}: {candidate[:100]}")
            return "PART_A"
        elif has_part_b:
            logger.info(f"Classified as PART_B from {source}: {candidate[:100]}")
            return "PART_B"
        else:
            logger.warning(
                f"No Part A/B indicator found in {source}: {candidate[:100]}, returning UNKNOWN"
            )
            return "UNKNOWN"

