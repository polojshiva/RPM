"""
Validations Service Client
HTTP client for calling HETS and PECOS validation services
"""
import time
import logging
from typing import Dict, Any, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class ValidationServiceError(Exception):
    """Custom exception for validation service errors"""
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ValidationsService:
    """
    HTTP client for HETS and PECOS validation services
    
    Handles proxying validation requests to external services with proper
    error handling, timeouts, and logging (without PHI).
    """
    
    def __init__(
        self,
        hets_base_url: Optional[str] = None,
        pecos_base_url: Optional[str] = None,
        connect_timeout: int = 5,
        read_timeout: int = 30
    ):
        """
        Initialize validation services client
        
        Args:
            hets_base_url: Base URL for HETS service (defaults to env var)
            pecos_base_url: Base URL for PECOS service (defaults to env var)
            connect_timeout: Connection timeout in seconds (default: 5s)
            read_timeout: Read timeout in seconds (default: 30s)
        """
        # HETS Configuration
        self.hets_base_url = (hets_base_url or getattr(settings, 'hets_base_url', '')).rstrip('/')
        self.hets_endpoint = "/eligibility"  # HETS endpoint path (matches Swagger: /eligibility)
        
        # PECOS Configuration
        self.pecos_base_url = (pecos_base_url or getattr(settings, 'pecos_base_url', '')).rstrip('/')
        self.pecos_endpoint_template = "/api/v1/npi/lookup/{npi}"  # PECOS endpoint template
        
        # Timeout configuration
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        # httpx.Timeout requires either a default or all four parameters (connect, read, write, pool)
        self.timeout = httpx.Timeout(
            timeout=read_timeout,  # Default timeout for all operations
            connect=connect_timeout  # Specific connect timeout
        )
        
        # Validate configuration
        if not self.hets_base_url:
            logger.warning("HETS_BASE_URL not configured - HETS validation will fail")
        if not self.pecos_base_url:
            logger.warning("PECOS_BASE_URL not configured - PECOS validation will fail")
        
        logger.info(
            f"ValidationsService initialized: "
            f"hets_base_url={self.hets_base_url}, "
            f"pecos_base_url={self.pecos_base_url}, "
            f"timeout=connect:{connect_timeout}s,read:{read_timeout}s"
        )
    
    async def validate_hets(
        self,
        payer: str,
        provider_npi: str,
        patient_mbi: str,
        patient_dob: str,
        patient_last_name: str,
        patient_first_name: str,
        criteria: str,
        date_of_service: str
    ) -> Dict[str, Any]:
        """
        Validate eligibility using HETS service
        
        Args:
            payer: Payer name (e.g., "medicare")
            provider_npi: Provider NPI (10 digits)
            patient_mbi: Patient Medicare Beneficiary Identifier
            patient_dob: Patient date of birth (ISO format: YYYY-MM-DD)
            patient_last_name: Patient last name
            patient_first_name: Patient first name
            criteria: Validation criteria (e.g., "Test" or "Production") - defaults to "Production"
            date_of_service: Date of service (string format as provided) - required
            
        Returns:
            Raw JSON response from HETS service (passthrough)
            
        Raises:
            ValidationServiceError: If validation fails
        """
        if not self.hets_base_url:
            raise ValidationServiceError("HETS service is not configured (HETS_BASE_URL missing)")
        
        endpoint_url = f"{self.hets_base_url}{self.hets_endpoint}"
        
        # Build request payload (criteria defaults to "Production" if not provided)
        payload = {
            "payer": payer,
            "provider": {
                "npi": provider_npi
            },
            "patient": {
                "mbi": patient_mbi,
                "dob": patient_dob,
                "lastName": patient_last_name,
                "firstName": patient_first_name
            },
            "criteria": criteria,
            "dateOfService": date_of_service
        }
        
        # Log request metadata (without PHI)
        logger.info(
            f"HETS validation request: payer={payer}, "
            f"provider_npi={provider_npi[:3]}***"
        )
        
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    endpoint_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Check response status
                if response.status_code == 200:
                    result = response.json()
                    
                    # Extract metadata for logging (without PHI)
                    request_id = result.get('request_id') or result.get('requestId') or 'N/A'
                    success = result.get('success', result.get('eligible', None))
                    
                    logger.info(
                        f"HETS validation completed: "
                        f"status=200, "
                        f"request_id={request_id}, "
                        f"success={success}, "
                        f"duration={duration_ms}ms"
                    )
                    
                    return result
                
                elif response.status_code >= 500:
                    # Server error
                    error_msg = f"HETS service returned {response.status_code}"
                    logger.error(
                        f"HETS validation failed: {error_msg}, duration={duration_ms}ms"
                    )
                    raise ValidationServiceError(
                        f"HETS service unavailable: {error_msg}"
                    )
                
                else:
                    # Client error (4xx)
                    try:
                        error_body = response.json()
                        error_detail = error_body.get('error') or error_body.get('message') or 'Unknown error'
                    except:
                        error_detail = response.text[:200] if response.text else 'Unknown error'
                    
                    logger.warning(
                        f"HETS validation client error: "
                        f"status={response.status_code}, "
                        f"detail={error_detail[:100]}, "
                        f"duration={duration_ms}ms"
                    )
                    
                    raise ValidationServiceError(
                        f"HETS validation failed: {error_detail} (status: {response.status_code})",
                        status_code=response.status_code
                    )
        
        except httpx.TimeoutException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"HETS request timeout after {self.read_timeout}s"
            logger.error(f"HETS validation timeout: {error_msg}, duration={duration_ms}ms")
            raise ValidationServiceError(error_msg, status_code=504) from e
        
        except httpx.ConnectError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Unable to connect to HETS service"
            logger.error(f"HETS validation connection error: {error_msg}, duration={duration_ms}ms")
            raise ValidationServiceError(error_msg, status_code=503) from e
        
        except httpx.RequestError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"HETS request failed: {str(e)}"
            logger.error(f"HETS validation request error: {error_msg}, duration={duration_ms}ms")
            raise ValidationServiceError(error_msg, status_code=503) from e
    
    async def validate_pecos(self, npi: str) -> Dict[str, Any]:
        """
        Validate provider enrollment using PECOS service
        
        Args:
            npi: Provider NPI (10 digits)
            
        Returns:
            Raw JSON response from PECOS service (passthrough)
            
        Raises:
            ValidationServiceError: If validation fails
        """
        if not self.pecos_base_url:
            raise ValidationServiceError("PECOS service is not configured (PECOS_BASE_URL missing)")
        
        endpoint_url = f"{self.pecos_base_url}{self.pecos_endpoint_template.format(npi=npi)}"
        
        # Log request metadata (without PHI)
        logger.info(f"PECOS validation request: npi={npi[:3]}***")
        
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    endpoint_url,
                    headers={
                        "Accept": "application/json"
                    }
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                # Check response status
                if response.status_code == 200:
                    result = response.json()
                    
                    # Extract metadata for logging
                    success = result.get('success', result.get('enrolled', None))
                    provider_name = result.get('provider_name') or result.get('name') or 'N/A'
                    
                    logger.info(
                        f"PECOS validation completed: "
                        f"status=200, "
                        f"success={success}, "
                        f"provider_name={provider_name[:50] if isinstance(provider_name, str) else 'N/A'}, "
                        f"duration={duration_ms}ms"
                    )
                    
                    return result
                
                elif response.status_code >= 500:
                    # Server error
                    error_msg = f"PECOS service returned {response.status_code}"
                    logger.error(
                        f"PECOS validation failed: {error_msg}, duration={duration_ms}ms"
                    )
                    raise ValidationServiceError(
                        f"PECOS service unavailable: {error_msg}"
                    )
                
                else:
                    # Client error (4xx)
                    try:
                        error_body = response.json()
                        error_detail = error_body.get('error') or error_body.get('message') or 'Unknown error'
                    except:
                        error_detail = response.text[:200] if response.text else 'Unknown error'
                    
                    logger.warning(
                        f"PECOS validation client error: "
                        f"status={response.status_code}, "
                        f"detail={error_detail[:100]}, "
                        f"duration={duration_ms}ms"
                    )
                    
                    raise ValidationServiceError(
                        f"PECOS validation failed: {error_detail} (status: {response.status_code})",
                        status_code=response.status_code
                    )
        
        except httpx.TimeoutException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"PECOS request timeout after {self.read_timeout}s"
            logger.error(f"PECOS validation timeout: {error_msg}, duration={duration_ms}ms")
            raise ValidationServiceError(error_msg, status_code=504) from e
        
        except httpx.ConnectError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = "Unable to connect to PECOS service"
            logger.error(f"PECOS validation connection error: {error_msg}, duration={duration_ms}ms")
            raise ValidationServiceError(error_msg, status_code=503) from e
        
        except httpx.RequestError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"PECOS request failed: {str(e)}"
            logger.error(f"PECOS validation request error: {error_msg}, duration={duration_ms}ms")
            raise ValidationServiceError(error_msg, status_code=503) from e

