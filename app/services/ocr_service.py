"""
OCR Service Client
HTTP client for calling the wiser-service-operations-ocr microservice
"""
import time
from pathlib import Path
from typing import Dict, Any, Optional
from logging import getLogger
import httpx

from app.config import settings

# Import httpx exceptions with fallback
try:
    from httpx import TimeoutException, RequestError
except ImportError:
    # Fallback for older httpx versions
    TimeoutException = Exception
    RequestError = Exception

logger = getLogger(__name__)


class OCRServiceError(Exception):
    """Custom exception for OCR service errors"""
    pass


class OCRService:
    """
    HTTP client for OCR service
    
    Calls the wiser-service-operations-ocr microservice to process PDF pages.
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        max_retries: Optional[int] = None
    ):
        """
        Initialize OCR service client
        
        Args:
            base_url: Base URL for OCR service (defaults to OCR_BASE_URL from settings)
            timeout_seconds: Request timeout in seconds (defaults to OCR_TIMEOUT_SECONDS from settings)
            max_retries: Maximum retry attempts for transient failures (defaults to OCR_MAX_RETRIES from settings)
        """
        self.base_url = (base_url or settings.ocr_base_url).rstrip('/')
        self.timeout_seconds = timeout_seconds or settings.ocr_timeout_seconds
        self.max_retries = max_retries or settings.ocr_max_retries
        
        if not self.base_url:
            raise OCRServiceError(
                "OCR_BASE_URL must be set. Configure OCR_BASE_URL environment variable."
            )
        
        # Construct full endpoint URL
        self.endpoint_url = f"{self.base_url}/api/v1/ocr/coversheet"
        
        logger.info(
            f"OCRService initialized: base_url={self.base_url}, "
            f"timeout={self.timeout_seconds}s, max_retries={self.max_retries}"
        )
    
    def run_ocr_on_pdf(self, local_pdf_path: str) -> Dict[str, Any]:
        """
        Run OCR on a local PDF file
        
        Args:
            local_pdf_path: Path to local PDF file
            
        Returns:
            Normalized OCR response dictionary with:
            - doc_type: str
            - overall_document_confidence: float
            - model_id: str
            - coversheet_type: str
            - fields: Dict[str, Dict] with keys: value, confidence, field_type
            
        Raises:
            OCRServiceError: If OCR processing fails after retries
        """
        pdf_path = Path(local_pdf_path)
        
        if not pdf_path.exists():
            raise OCRServiceError(f"PDF file does not exist: {local_pdf_path}")
        
        if not pdf_path.is_file():
            raise OCRServiceError(f"Path is not a file: {local_pdf_path}")
        
        logger.info(f"Running OCR on PDF: {local_pdf_path} ({pdf_path.stat().st_size} bytes)")
        
        # Read file content
        try:
            with open(pdf_path, 'rb') as f:
                file_content = f.read()
        except Exception as e:
            raise OCRServiceError(f"Failed to read PDF file {local_pdf_path}: {e}") from e
        
        # Retry logic for transient failures
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                start_time = time.time()
                
                # Prepare multipart form data
                files = {
                    'file': (pdf_path.name, file_content, 'application/pdf')
                }
                
                # Make HTTP request
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(
                        self.endpoint_url,
                        files=files,
                        params={'order_mode': 'service'}  # Use service order mode
                    )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Check response status
                if response.status_code == 200:
                    result = response.json()
                    
                    # Normalize response format
                    normalized = self._normalize_response(result, duration_ms)
                    
                    logger.info(
                        f"OCR completed successfully: {local_pdf_path} "
                        f"(confidence={normalized.get('overall_document_confidence', 0):.2f}, "
                        f"fields={len(normalized.get('fields', {}))}, duration={duration_ms}ms)"
                    )
                    
                    return normalized
                
                elif response.status_code >= 500:
                    # Server error (502 Bad Gateway, 503 Service Unavailable, etc.) - retry with longer backoff
                    error_msg = f"OCR service returned {response.status_code}: {response.text[:200]}"
                    logger.warning(
                        f"OCR service error (attempt {attempt}/{self.max_retries}): {error_msg}"
                    )
                    last_error = OCRServiceError(error_msg)
                    
                    if attempt < self.max_retries:
                        # Exponential backoff with longer delays for 502/503 errors
                        # 502/503 indicate service overload, so use longer backoff
                        if response.status_code in [502, 503]:
                            wait_time = 2 ** attempt  # Longer backoff: 2s, 4s, 8s, 16s, 32s
                        else:
                            wait_time = 2 ** (attempt - 1)  # Standard backoff: 1s, 2s, 4s
                        logger.info(f"Retrying OCR in {wait_time} seconds...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise last_error
                
                else:
                    # Client error (4xx) - don't retry
                    error_msg = f"OCR service returned {response.status_code}: {response.text[:200]}"
                    logger.error(f"OCR service client error: {error_msg}")
                    raise OCRServiceError(error_msg)
            
            except TimeoutException as e:
                error_msg = f"OCR request timeout after {self.timeout_seconds}s"
                logger.warning(
                    f"OCR timeout (attempt {attempt}/{self.max_retries}): {error_msg}"
                )
                last_error = OCRServiceError(f"{error_msg}: {e}")
                
                if attempt < self.max_retries:
                    wait_time = 2 ** (attempt - 1)
                    logger.info(f"Retrying OCR in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise last_error
            
            except RequestError as e:
                error_msg = f"OCR request failed: {e}"
                logger.warning(
                    f"OCR request error (attempt {attempt}/{self.max_retries}): {error_msg}"
                )
                last_error = OCRServiceError(f"{error_msg}: {e}")
                
                if attempt < self.max_retries:
                    wait_time = 2 ** (attempt - 1)
                    logger.info(f"Retrying OCR in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise last_error
        
        # If we get here, all retries failed
        raise last_error or OCRServiceError("OCR processing failed after all retries")
    
    def _normalize_response(self, raw_response: Dict[str, Any], duration_ms: int) -> Dict[str, Any]:
        """
        Normalize OCR service response to consistent format
        
        Args:
            raw_response: Raw JSON response from OCR service
            duration_ms: Processing duration in milliseconds
            
        Returns:
            Normalized response dictionary
        """
        # Extract fields and normalize structure
        fields = {}
        raw_fields = raw_response.get('fields', {})
        
        for field_name, field_data in raw_fields.items():
            if isinstance(field_data, dict):
                fields[field_name] = {
                    'value': field_data.get('value', ''),
                    'confidence': field_data.get('confidence', 0.0),
                    'field_type': field_data.get('field_type', 'STRING')
                }
            else:
                # Handle legacy format if needed
                fields[field_name] = {
                    'value': str(field_data) if field_data else '',
                    'confidence': 0.0,
                    'field_type': 'STRING'
                }
        
        return {
            'doc_type': raw_response.get('doc_type', 'coversheet-extraction'),
            'overall_document_confidence': raw_response.get('overall_document_confidence', 0.0),
            'model_id': raw_response.get('model_id', 'coversheet-extraction'),
            'coversheet_type': raw_response.get('coversheet_type', ''),
            'fields': fields,
            'duration_ms': duration_ms,
            'raw': raw_response  # Store raw response for debugging
        }

