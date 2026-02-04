"""
Application Settings
Centralized configuration using Pydantic Settings
"""
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from functools import lru_cache


# Default development secrets - never use in production
_DEV_JWT_SECRET = "dev-jwt-secret-key-for-testing"
_DEV_REFRESH_SECRET = "dev-refresh-secret-key-for-testing"


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Server
    port: int = 4000
    host: str = "0.0.0.0"
    env: str = "development"

    # CORS - Frontend Integration
    # Default development URLs for common frontend ports
    # In production, set CORS_ORIGINS environment variable with specific allowed origins
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,http://localhost:5173"

    # JWT
    jwt_secret: str = _DEV_JWT_SECRET
    refresh_token_secret: str = _DEV_REFRESH_SECRET
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Audit
    audit_log_path: str = "./audit.log"

    # Azure AD Configuration
    azure_tenant_id: str = ""
    azure_client_id: str = ""

    # Logging
    log_level: str = "INFO"

    # Cookies
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # Mock User Passwords (development only)
    mock_admin_password: str = "adminpass"
    mock_reviewer_password: str = "reviewerpass"
    mock_coordinator_password: str = "coordinatorpass"
    mock_guest_password: str = "guestpass"
    
    # Message Poller Configuration
    message_poller_enabled: bool = True
    message_poller_interval_seconds: int = 180  # Poll every N seconds (default: 3 minutes, configurable via MESSAGE_POLLER_INTERVAL_SECONDS env var)
    message_poller_batch_size: int = 7  # Process up to 7 messages per poll (increased from 3 for faster processing)
    
    # ClinicalOps Poller Configuration
    clinical_ops_poller_enabled: bool = True
    clinical_ops_poll_interval_seconds: int = 60  # Poll every 60s (1 min). Override: CLINICAL_OPS_POLL_INTERVAL_SECONDS
    clinical_ops_poll_batch_size: int = 25  # Process up to 25 messages per poll. Override: CLINICAL_OPS_POLL_BATCH_SIZE
    clinical_ops_processing_delay_seconds: float = 2.0  # Delay between messages (prevents pool exhaustion). Override: CLINICAL_OPS_PROCESSING_DELAY_SECONDS
    
    # Azure Blob Storage Configuration
    storage_account_url: str = ""  # e.g., https://devwisersa.blob.core.windows.net
    azure_storage_connection_string: Optional[str] = None  # For dev/local (optional, uses DefaultAzureCredential if not set)
    
    # Container Configuration (SOURCE vs DEST separation)
    # SOURCE: Read-only container owned by Integration layer (e.g., "esmd-download")
    azure_storage_source_container: str = ""  # Required: Source container for downloading original documents
    # DEST: Write-only container owned by ServiceOps (e.g., "service-ops-processing")
    azure_storage_dest_container: str = ""  # Required: Destination container for uploading split pages and artifacts
    
    # Legacy/Backward compatibility (deprecated - use SOURCE/DEST instead)
    container_name: str = ""  # DEPRECATED: Use azure_storage_source_container instead. Kept for backward compatibility.
    
    # Blob Path Prefix Configuration
    azure_storage_blob_prefix: Optional[str] = None  # Optional prefix for blob paths (e.g., "service_ops_processing"). If set, all blob reads will use {prefix}/{relative_path}. Sanitized: leading/trailing slashes and whitespace are stripped.
    
    blob_temp_dir: str = "/tmp/service_ops_blobs"  # Base directory for temporary files
    blob_max_retries: int = 5  # Maximum retry attempts for transient failures
    blob_retry_base_seconds: float = 1.0  # Base delay in seconds for exponential backoff
    
    # OCR Service Configuration
    ocr_base_url: str = ""  # Base URL for OCR service (e.g., http://localhost:5080)
    ocr_timeout_seconds: int = 120  # Request timeout in seconds (default: 2 minutes)
    ocr_max_retries: int = 5  # Maximum retry attempts for transient failures (5xx, timeouts) - increased from 3
    ocr_confidence_threshold: float = 0.5  # Minimum confidence threshold for field counting in coversheet detection (0.0-1.0)
    ocr_delay_between_requests: float = 0.5  # Delay in seconds between OCR requests to reduce load (default: 0.5s)
    ocr_retry_failed_pages: bool = True  # Retry failed pages at end of processing (default: True)
    ocr_max_failed_page_retries: int = 3  # Maximum retries for failed pages at end (default: 3)
    ocr_stop_after_coversheet: bool = True  # Stop processing pages after finding strong coversheet candidate (default: True)
    ocr_coversheet_confidence_threshold: float = 0.7  # Minimum confidence to consider a page as strong coversheet candidate (default: 0.7)
    ocr_min_coversheet_fields: int = 20  # Minimum number of fields to consider a page as strong coversheet candidate (default: 20)
    
    # Validation Services Configuration
    hets_base_url: str = ""  # Base URL for HETS service (DEV: https://dev-wiser-hets-api-b7bqh0gshnftc7f4.eastus-01.azurewebsites.net, PROD: https://prd-wiser-hets-app.azurewebsites.us)
    pecos_base_url: str = ""  # Base URL for PECOS service (DEV: https://dev-wiser-pecos-api.azurewebsites.net, PROD: https://prd-wiser-pecos-app.azurewebsites.us)
    hets_criteria: Optional[str] = None  # HETS validation criteria (e.g., 'Production'). If not set and env is production, validation will fail. If not set and env is not production, defaults to 'Production'.
    validations_connect_timeout: int = 5  # Connection timeout in seconds (default: 5s)
    validations_read_timeout: int = 30  # Read timeout in seconds (default: 30s)
    
    # LetterGen API Configuration
    lettergen_base_url: str = ""  # Base URL for LetterGen API (e.g., https://lettergen-api.example.com)
    lettergen_timeout_seconds: int = 60  # Request timeout in seconds (default: 60s)
    lettergen_max_retries: int = 3  # Maximum retry attempts for transient failures (5xx, timeouts)
    lettergen_retry_base_seconds: float = 1.0  # Base delay in seconds for exponential backoff
    
    # JSON Generator Service Configuration
    json_generator_base_url: str = ""  # Base URL for JSON Generator service (e.g., https://prd-wiser-pa-decision-payload-json-generator.azurewebsites.us)
    json_generator_timeout_seconds: int = 180  # Request timeout in seconds (increased from 60s to 180s for stability)
    json_generator_connect_timeout_seconds: int = 30  # Connection timeout in seconds (separate from read timeout)
    json_generator_max_retries: int = 3  # Maximum retry attempts for transient failures (timeouts, 5xx errors)
    json_generator_retry_base_seconds: float = 2.0  # Base delay in seconds for exponential backoff
    
    # Database Connection Pool Configuration
    # Increased to 80 for better reliability and to handle connection pool exhaustion scenarios
    # pool_size=80 + max_overflow=120 = 200 total connections (configurable via DB_POOL_SIZE env var)
    db_pool_size: int = 80  # Number of connections to maintain in pool (increased from 20, configurable via DB_POOL_SIZE)
    db_max_overflow: int = 120  # Maximum overflow connections beyond pool_size (1.5x pool_size for safety)
    
    @model_validator(mode="after")
    def validate_pool_size(self):
        """Validate database pool size is within reasonable bounds"""
        if self.db_pool_size < 5:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"db_pool_size ({self.db_pool_size}) is too small, setting to minimum 5")
            self.db_pool_size = 5
        elif self.db_pool_size > 200:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"db_pool_size ({self.db_pool_size}) is too large, setting to maximum 200")
            self.db_pool_size = 200
        
        # Adjust max_overflow proportionally (1.5x pool_size)
        self.db_max_overflow = int(self.db_pool_size * 1.5)
        
        return self
    db_pool_timeout: int = 30  # Seconds to wait before giving up on getting connection from pool
    db_pool_recycle: int = 1800  # Seconds before recycling a connection (30 minutes - shorter than DB idle timeout)
    db_pool_pre_ping: bool = True  # Verify connections before using (recommended)
    db_connect_args_connect_timeout: int = 10  # Connection timeout in seconds
    db_echo: bool = False  # Log all SQL statements (set to True for debugging)
    
    # Public Base URL Configuration
    # Optional: If set, this will be used as the base URL for generating preview URLs
    # Useful in Gov environments where X-Forwarded-Proto headers may not be forwarded correctly
    # Example: https://prd-wiser-ops-appb.azurewebsites.us
    public_base_url: Optional[str] = None

    #Allow extra fields in your Settings class by adding model_config = {"extra": "allow"} (for Pydantic v2) inside your Settings class
    model_config = {
        "extra": "allow", 
        "env_file": ".env", 
        "env_file_encoding": "utf-8", 
        "case_sensitive": False
        }

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.env.lower() == "production"
    
    def get_hets_criteria(self) -> str:
        """
        Get HETS criteria value with fallback logic:
        - If HETS_CRITERIA env var is set, use it
        - If not set and NOT in production, default to 'Production'
        - If not set and IN production, raise error (must be explicitly set)
        """
        if self.hets_criteria:
            return self.hets_criteria.strip()
        
        if not self.is_production:
            # Non-production: use default
            return "Production"
        
        # Production: must be explicitly set
        raise ValueError(
            "HETS_CRITERIA environment variable must be set in production. "
            "This is a critical field and cannot use default values in production."
        )

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Ensure production environment uses secure secrets"""
        if self.is_production:
            if self.jwt_secret == _DEV_JWT_SECRET:
                raise ValueError(
                    "Production environment requires a secure JWT_SECRET. "
                    "Do not use development defaults in production."
                )
            if self.refresh_token_secret == _DEV_REFRESH_SECRET:
                raise ValueError(
                    "Production environment requires a secure REFRESH_TOKEN_SECRET. "
                    "Do not use development defaults in production."
                )
            if not self.cookie_secure:
                raise ValueError(
                    "Production environment requires COOKIE_SECURE=true for secure cookies."
                )
        return self
    
    def validate_storage_containers(self) -> None:
        """
        Validate SOURCE and DEST container configuration.
        
        This is called lazily when blob storage is actually used (DocumentProcessor, BlobStorageClient),
        not at Settings initialization, to allow tests to run without full configuration.
        """
        # Resolve SOURCE container (check new var first, then legacy)
        source_container = self.azure_storage_source_container or self.container_name
        
        # Validate SOURCE container is set
        if not source_container or not source_container.strip():
            raise ValueError(
                "AZURE_STORAGE_SOURCE_CONTAINER (or CONTAINER_NAME for backward compatibility) "
                "must be set. This is the read-only source container for downloading original documents."
            )
        
        # Validate DEST container is set
        if not self.azure_storage_dest_container or not self.azure_storage_dest_container.strip():
            raise ValueError(
                "AZURE_STORAGE_DEST_CONTAINER must be set. "
                "This is the write-only destination container for uploading split pages and artifacts."
            )
        
        # CRITICAL SAFETY CHECK: SOURCE and DEST must be different
        if source_container.strip() == self.azure_storage_dest_container.strip():
            raise ValueError(
                f"AZURE_STORAGE_SOURCE_CONTAINER ({source_container}) and "
                f"AZURE_STORAGE_DEST_CONTAINER ({self.azure_storage_dest_container}) must be different. "
                f"ServiceOps must NEVER upload to the Integration-owned SOURCE container."
            )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


settings = get_settings()
