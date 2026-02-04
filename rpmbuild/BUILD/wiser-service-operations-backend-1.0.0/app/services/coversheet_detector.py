"""
Coversheet Detector
Detects which page in a multi-page document is the coversheet
"""
from typing import List, Dict, Any, Optional
from logging import getLogger

from app.config import settings

logger = getLogger(__name__)


class CoversheetDetector:
    """
    Detects the coversheet page from OCR results
    
    Uses heuristics to identify which page contains the most relevant fields
    with highest confidence scores.
    """
    
    def __init__(self, confidence_threshold: Optional[float] = None):
        """
        Initialize coversheet detector
        
        Args:
            confidence_threshold: Minimum confidence threshold for field counting (defaults to OCR_CONFIDENCE_THRESHOLD from settings)
        """
        self.confidence_threshold = confidence_threshold or settings.ocr_confidence_threshold
        
        if self.confidence_threshold < 0.0 or self.confidence_threshold > 1.0:
            raise ValueError(
                f"confidence_threshold must be between 0.0 and 1.0, got: {self.confidence_threshold}"
            )
        
        logger.info(
            f"CoversheetDetector initialized with confidence_threshold={self.confidence_threshold}"
        )
    
    def detect_coversheet_page(
        self,
        page_ocr_results: List[Dict[str, Any]]
    ) -> int:
        """
        Detect which page is the coversheet
        
        Args:
            page_ocr_results: List of OCR results per page, each dict should have:
                - page_number: int (1-based)
                - fields: Dict[str, Dict] with keys: value, confidence, field_type
                - overall_document_confidence: float (optional)
        
        Returns:
            Page number (1-based) of the detected coversheet
            
        Raises:
            ValueError: If page_ocr_results is empty or invalid
        """
        if not page_ocr_results:
            raise ValueError("page_ocr_results cannot be empty")
        
        if len(page_ocr_results) == 1:
            # Single page document - must be the coversheet
            page_num = page_ocr_results[0].get('page_number', 1)
            logger.info(f"Single page document detected, coversheet is page {page_num}")
            return page_num
        
        # Score each page based on field count and confidence
        page_scores = []
        
        for page_result in page_ocr_results:
            page_number = page_result.get('page_number', 0)
            if page_number < 1:
                logger.warning(f"Invalid page_number {page_number}, skipping")
                continue
            
            fields = page_result.get('fields', {})
            if not isinstance(fields, dict):
                logger.warning(f"Invalid fields format for page {page_number}, skipping")
                continue
            
            # Count fields with confidence >= threshold
            high_confidence_count = 0
            total_confidence = 0.0
            confidence_count = 0
            
            for field_name, field_data in fields.items():
                if isinstance(field_data, dict):
                    confidence = field_data.get('confidence', 0.0)
                    value = field_data.get('value', '')
                    
                    # Only count non-empty fields
                    if value and value.strip():
                        if confidence >= self.confidence_threshold:
                            high_confidence_count += 1
                        
                        total_confidence += confidence
                        confidence_count += 1
            
            # Calculate average confidence (only for non-empty fields)
            avg_confidence = total_confidence / confidence_count if confidence_count > 0 else 0.0
            
            # Score: prioritize high-confidence field count, then average confidence
            # Use a weighted score: (field_count * 100) + (avg_confidence * 10)
            score = (high_confidence_count * 100) + (avg_confidence * 10)
            
            page_scores.append({
                'page_number': page_number,
                'high_confidence_count': high_confidence_count,
                'avg_confidence': avg_confidence,
                'total_fields': len(fields),
                'score': score
            })
            
            logger.debug(
                f"Page {page_number}: {high_confidence_count} high-confidence fields, "
                f"avg_confidence={avg_confidence:.3f}, score={score:.1f}"
            )
        
        if not page_scores:
            # Fallback: return first page
            logger.warning("No valid pages found, defaulting to page 1")
            return 1
        
        # Sort by score (descending), then by page_number (ascending) for tie-breaking
        page_scores.sort(key=lambda x: (-x['score'], x['page_number']))
        
        best_page = page_scores[0]
        coversheet_page = best_page['page_number']
        
        logger.info(
            f"Detected coversheet: page {coversheet_page} "
            f"(score={best_page['score']:.1f}, "
            f"high_confidence_fields={best_page['high_confidence_count']}, "
            f"avg_confidence={best_page['avg_confidence']:.3f})"
        )
        
        return coversheet_page

