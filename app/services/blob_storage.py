"""
Azure Blob Storage Client
Handles downloading source documents and uploading derived artifacts (split pages)
Supports both connection string and Managed Identity authentication
"""
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional, Any
from urllib.parse import urlparse

from azure.storage.blob import BlobServiceClient, BlobClient, ContentSettings, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import (
    AzureError,
    ResourceNotFoundError,
    HttpResponseError,
    ServiceRequestError,
)
from azure.identity import DefaultAzureCredential
from datetime import datetime, timedelta

from app.config import settings
from app.utils.blob_path_helper import resolve_blob_path, log_blob_access

logger = logging.getLogger(__name__)


class BlobStorageError(Exception):
    """Custom exception for blob storage operations"""
    pass


class BlobStorageClient:
    """
    Azure Blob Storage client for downloading and uploading files.
    
    Supports:
    - Connection string authentication (dev/local)
    - Managed Identity / DefaultAzureCredential (prod on Azure)
    - Both absolute URLs and relative blob paths
    - Retry logic for transient failures
    - Stream downloads to avoid memory issues
    """
    
    def __init__(
        self,
        storage_account_url: Optional[str] = None,
        container_name: Optional[str] = None,
        connection_string: Optional[str] = None,
        temp_dir: Optional[str] = None,
        max_retries: Optional[int] = None,
        retry_base_seconds: Optional[float] = None,
    ):
        """
        Initialize blob storage client.
        
        Args:
            storage_account_url: Base URL for storage account (e.g., https://devwisersa.blob.core.windows.net)
            container_name: Container name (e.g., esmd-download)
            connection_string: Azure storage connection string (optional, uses DefaultAzureCredential if not provided)
            temp_dir: Base directory for temporary files (default: /tmp/service_ops_blobs)
            max_retries: Maximum retry attempts for transient failures (default: 5)
            retry_base_seconds: Base delay in seconds for exponential backoff (default: 1.0)
        """
        self.storage_account_url = storage_account_url or settings.storage_account_url
        # container_name is optional - we use per-call container names in methods
        # Set default from SOURCE container for backward compatibility, but it's not required
        self.container_name = container_name or settings.container_name or settings.azure_storage_source_container or ""
        self.temp_dir = Path(temp_dir or settings.blob_temp_dir)
        self.max_retries = max_retries or settings.blob_max_retries
        self.retry_base_seconds = retry_base_seconds or settings.blob_retry_base_seconds
        
        # Ensure temp directory exists
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize blob service client
        self._blob_service_client: Optional[BlobServiceClient] = None
        self._connection_string = connection_string or settings.azure_storage_connection_string
        
        if not self.storage_account_url:
            raise BlobStorageError(
                "storage_account_url is required. Set AZURE_STORAGE_ACCOUNT_URL environment variable."
            )
        # container_name is optional at init since we use per-call containers in all methods
        # No validation needed here - methods will validate container_name when called
        
        logger.info(
            f"BlobStorageClient initialized: account_url={self.storage_account_url}, "
            f"default_container={self.container_name or '(per-call containers)'}, temp_dir={self.temp_dir}"
        )
    
    def _get_blob_service_client(self) -> BlobServiceClient:
        """
        Get or create blob service client with appropriate authentication.
        
        Returns:
            BlobServiceClient instance
        """
        if self._blob_service_client is None:
            try:
                if self._connection_string:
                    # Use connection string (dev/local)
                    logger.debug("Using connection string authentication")
                    self._blob_service_client = BlobServiceClient.from_connection_string(
                        self._connection_string
                    )
                else:
                    # Use Managed Identity / DefaultAzureCredential (prod)
                    logger.debug("Using DefaultAzureCredential (Managed Identity)")
                    credential = DefaultAzureCredential()
                    self._blob_service_client = BlobServiceClient(
                        account_url=self.storage_account_url,
                        credential=credential
                    )
            except Exception as e:
                logger.error(f"Failed to initialize blob service client: {e}", exc_info=True)
                raise BlobStorageError(f"Failed to initialize blob service client: {e}") from e
        
        return self._blob_service_client
    
    def _get_blob_client(self, blob_path_or_url: str, container_name: Optional[str] = None) -> BlobClient:
        """
        Get blob client for a given blob path or URL.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            container_name: Optional container name override (if None, uses instance container_name)
            
        Returns:
            BlobClient instance
        """
        # If absolute URL, extract container from URL; otherwise use provided or instance container
        if blob_path_or_url.startswith('http://') or blob_path_or_url.startswith('https://'):
            # Parse URL to extract container and blob name
            parsed = urlparse(blob_path_or_url)
            path_parts = parsed.path.lstrip('/').split('/', 1)
            if len(path_parts) > 1:
                container_from_url = path_parts[0]
                blob_name = path_parts[1]
            else:
                container_from_url = None
                blob_name = path_parts[0] if path_parts else ''
            
            # Use container from URL if present, otherwise use provided or instance container
            target_container = container_from_url or container_name or self.container_name
        else:
            # Relative path - resolve with prefix helper
            target_container = container_name or self.container_name
            # Apply blob prefix if configured
            resolved_blob_path = resolve_blob_path(blob_path_or_url)
            
            # Resolve to absolute URL for blob name extraction
            blob_url = self.resolve_blob_url(resolved_blob_path, target_container)
            parsed = urlparse(blob_url)
            path_parts = parsed.path.lstrip('/').split('/', 1)
            if len(path_parts) > 1:
                blob_name = path_parts[1]
            else:
                blob_name = path_parts[0] if path_parts else ''
            
            # Log for debugging blob path extraction with prefix resolution
            logger.debug(
                f"_get_blob_client: relative_path='{blob_path_or_url}', "
                f"resolved_with_prefix='{resolved_blob_path}', "
                f"target_container='{target_container}', resolved_url='{blob_url}', "
                f"extracted_blob_name='{blob_name}'"
            )
        
        if not target_container:
            raise BlobStorageError(
                f"container_name is required. Provide container_name parameter or set default container."
            )
        
        service_client = self._get_blob_service_client()
        blob_client = service_client.get_blob_client(container=target_container, blob=blob_name)
        
        # Log final blob client configuration for verification
        logger.debug(
            f"_get_blob_client: Created BlobClient with container='{blob_client.container_name}', "
            f"blob='{blob_client.blob_name}'"
        )
        
        return blob_client
    
    def generate_signed_url(
        self, 
        blob_path_or_url: str, 
        container_name: Optional[str] = None,
        expiry_minutes: int = 60
    ) -> str:
        """
        Generate a signed URL (with SAS token) for a blob.
        Required when storage account doesn't allow public access.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            container_name: Optional container name override
            expiry_minutes: Minutes until SAS token expires (default: 60)
            
        Returns:
            Signed URL with SAS token
            
        Raises:
            BlobStorageError: If SAS token generation fails
        """
        try:
            # Get blob client to extract container and blob name
            blob_client = self._get_blob_client(blob_path_or_url, container_name=container_name)
            container = blob_client.container_name
            blob_name = blob_client.blob_name
            
            # Extract account name from storage account URL
            parsed = urlparse(self.storage_account_url)
            account_name = parsed.netloc.split('.')[0]
            
            # Generate SAS token
            # Try to extract account key from connection string if available
            account_key = None
            if self._connection_string:
                # Parse connection string: "AccountName=...;AccountKey=...;..."
                for part in self._connection_string.split(';'):
                    if part.startswith('AccountKey='):
                        account_key = part.split('=', 1)[1]
                        break
            
            if not account_key:
                # If no account key, we can't generate SAS token
                # Fall back to regular URL (will fail if public access disabled)
                logger.warning("No account key available for SAS token generation. Using regular URL.")
                return self.resolve_blob_url(blob_path_or_url, container_name=container_name)
            
            # Generate SAS token with read permission
            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=container,
                blob_name=blob_name,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(minutes=expiry_minutes)
            )
            
            # Construct signed URL
            base_url = self.resolve_blob_url(blob_path_or_url, container_name=container_name)
            signed_url = f"{base_url}?{sas_token}"
            
            logger.debug(f"Generated signed URL for blob: {blob_name} (expires in {expiry_minutes} minutes)")
            return signed_url
            
        except Exception as e:
            logger.error(f"Failed to generate signed URL: {e}", exc_info=True)
            raise BlobStorageError(f"Failed to generate signed URL: {e}") from e
    
    def resolve_blob_url(self, blob_path_or_url: str, container_name: Optional[str] = None) -> str:
        """
        Resolve blob path or URL to absolute URL.
        
        Args:
            blob_path_or_url: Either:
                - Absolute URL: https://{account}.blob.core.windows.net/{container}/v2/...
                - Relative path: v2/2026/01-03/... (will be combined with base URL + container + prefix if configured)
            container_name: Optional container name override (if None, uses instance container_name)
        
        Returns:
            Absolute blob URL
        """
        if not blob_path_or_url:
            raise BlobStorageError("blob_path_or_url cannot be empty")
        
        # If already absolute URL, return as-is
        if blob_path_or_url.startswith('http://') or blob_path_or_url.startswith('https://'):
            logger.debug(f"Resolved absolute URL: {blob_path_or_url}")
            return blob_path_or_url
        
        # Resolve relative path with prefix helper
        resolved_path = resolve_blob_path(blob_path_or_url)
        
        # Use provided container or instance container
        target_container = container_name or self.container_name
        if not target_container:
            raise BlobStorageError(
                "container_name is required to resolve relative path. "
                "Provide container_name parameter or set default container."
            )
        
        # Combine: storage_account_url/container_name/resolved_path
        base_url = self.storage_account_url.rstrip('/')
        container = target_container.strip('/')
        absolute_url = f"{base_url}/{container}/{resolved_path}"
        
        logger.debug(f"Resolved relative path '{blob_path_or_url}' (with prefix) to: {absolute_url} (container: {container})")
        return absolute_url
    
    def _retry_on_transient_failure(self, operation, *args, **kwargs):
        """
        Retry operation on transient failures with exponential backoff.
        
        Args:
            operation: Function to retry
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation
            
        Returns:
            Result of operation
            
        Raises:
            BlobStorageError: If operation fails after max retries
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                return operation(*args, **kwargs)
            except ResourceNotFoundError as e:
                # 404 Not Found - permanent error, don't retry
                logger.error(f"Blob not found (404): {e}")
                raise BlobStorageError(f"Blob not found: {e}") from e
            except HttpResponseError as e:
                # Check if it's a 5xx error (transient) or 4xx error (permanent)
                status_code = getattr(e, 'status_code', None)
                if status_code and status_code >= 500:
                    # 5xx errors - transient, retry
                    last_exception = e
                    if attempt < self.max_retries - 1:
                        wait_time = self.retry_base_seconds * (2 ** attempt)
                        logger.warning(
                            f"Transient failure (attempt {attempt + 1}/{self.max_retries}): {e}. "
                            f"Retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Operation failed after {self.max_retries} attempts: {e}")
                else:
                    # 4xx errors (except 404) - permanent, don't retry
                    logger.error(f"Client error (4xx): {e}")
                    raise BlobStorageError(f"Client error: {e}") from e
            except ServiceRequestError as e:
                # Network/connection errors - transient, retry
                last_exception = e
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_base_seconds * (2 ** attempt)
                    logger.warning(
                        f"Transient failure (attempt {attempt + 1}/{self.max_retries}): {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Operation failed after {self.max_retries} attempts: {e}")
            except AzureError as e:
                # Other Azure errors - don't retry
                logger.error(f"Azure error: {e}")
                raise BlobStorageError(f"Azure error: {e}") from e
        
        raise BlobStorageError(
            f"Operation failed after {self.max_retries} retries: {last_exception}"
        ) from last_exception
    
    def download_to_file(
        self,
        blob_path_or_url: str,
        local_path: str,
        container_name: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Download blob to local file path.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            local_path: Local file path where blob will be saved
            container_name: Optional container name override (if None, uses instance container_name)
            timeout: Download timeout in seconds (default: 300)
            
        Returns:
            Dict with metadata:
                - local_path: Path to downloaded file
                - size_bytes: File size in bytes
                - etag: Blob ETag
                - content_type: Content type
                - blob_url: Resolved blob URL
        """
        local_path_obj = Path(local_path)
        
        # Create parent directories if missing
        local_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # Resolve container for logging
        target_container = container_name or self.container_name
        
        # Resolve blob path with prefix for logging
        if not (blob_path_or_url.startswith('http://') or blob_path_or_url.startswith('https://')):
            resolved_path = resolve_blob_path(blob_path_or_url)
            log_blob_access(target_container, resolved_path)
        else:
            resolved_path = blob_path_or_url
        
        logger.info(
            f"Downloading blob from container '{target_container}': '{resolved_path}' to '{local_path}'"
        )
        
        def _download():
            blob_client = self._get_blob_client(blob_path_or_url, container_name=container_name)
            
            # Get blob properties first
            properties = blob_client.get_blob_properties()
            
            # Download with streaming to avoid memory issues
            with open(local_path, 'wb') as f:
                download_stream = blob_client.download_blob(timeout=timeout)
                download_stream.readinto(f)
            
            return {
                'local_path': str(local_path),
                'size_bytes': properties.size,
                'etag': properties.etag,
                'content_type': properties.content_settings.content_type if properties.content_settings else None,
                'blob_url': self.resolve_blob_url(blob_path_or_url, container_name=container_name),
            }
        
        try:
            result = self._retry_on_transient_failure(_download)
            logger.info(
                f"Successfully downloaded blob '{blob_path_or_url}' "
                f"({result['size_bytes']} bytes) to '{local_path}'"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to download blob '{blob_path_or_url}': {e}", exc_info=True)
            # Clean up partial file on error
            if local_path_obj.exists():
                try:
                    local_path_obj.unlink()
                except Exception:
                    pass
            raise BlobStorageError(f"Failed to download blob: {e}") from e
    
    def download_to_temp(
        self,
        blob_path_or_url: str,
        subdir: Optional[str] = None,
        container_name: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Download blob to temporary file.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            subdir: Optional subdirectory under temp_dir (e.g., 'documents', 'pages')
            container_name: Optional container name override (if None, uses instance container_name)
            timeout: Download timeout in seconds (default: 300)
            
        Returns:
            Dict with metadata (same as download_to_file)
        """
        # Create subdirectory if specified
        if subdir:
            temp_path = self.temp_dir / subdir
            temp_path.mkdir(parents=True, exist_ok=True)
        else:
            temp_path = self.temp_dir
        
        # Generate unique filename from blob path
        blob_name = os.path.basename(blob_path_or_url.rstrip('/'))
        if not blob_name:
            # Fallback: use hash or timestamp
            import hashlib
            blob_name = hashlib.md5(blob_path_or_url.encode()).hexdigest() + '.tmp'
        
        # Ensure unique filename
        local_path = temp_path / blob_name
        counter = 1
        while local_path.exists():
            stem = local_path.stem
            suffix = local_path.suffix
            local_path = temp_path / f"{stem}_{counter}{suffix}"
            counter += 1
        
        return self.download_to_file(blob_path_or_url, str(local_path), container_name=container_name, timeout=timeout)
    
    def upload_file(
        self,
        local_path: str,
        dest_blob_path: str,
        container_name: Optional[str] = None,
        overwrite: bool = True,
        content_type: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Upload local file to blob storage.
        
        Args:
            local_path: Path to local file to upload
            dest_blob_path: Destination blob path (relative to container)
            container_name: Optional container name override (if None, uses instance container_name)
            overwrite: Whether to overwrite if blob exists (default: True)
            content_type: Content type for blob (auto-detected if not provided)
            timeout: Upload timeout in seconds (default: 300)
            
        Returns:
            Dict with metadata:
                - blob_url: Absolute URL of uploaded blob
                - blob_path: Relative blob path
                - etag: Blob ETag
                - size_bytes: File size in bytes
                - content_type: Content type
                
        Raises:
            RuntimeError: If attempting to upload to SOURCE container
        """
        local_path_obj = Path(local_path)
        
        if not local_path_obj.exists():
            raise BlobStorageError(f"Local file does not exist: {local_path}")
        
        # Remove leading slash from dest_blob_path
        dest_blob_path = dest_blob_path.lstrip('/')
        
        # Resolve target container
        target_container = container_name or self.container_name
        if not target_container:
            raise BlobStorageError(
                "container_name must be provided for upload_file() or set as default container"
            )
        
        # CRITICAL SAFETY CHECK: Prevent uploading to SOURCE container
        source_container = settings.azure_storage_source_container or settings.container_name
        if source_container and target_container.strip() == source_container.strip():
            raise RuntimeError(
                f"SECURITY VIOLATION: Attempted to upload to SOURCE container '{target_container}'. "
                f"ServiceOps must NEVER upload to the Integration-owned SOURCE container. "
                f"Use AZURE_STORAGE_DEST_CONTAINER for uploads."
            )
        
        logger.info(
            f"Uploading file '{local_path}' to DEST container '{target_container}': blob '{dest_blob_path}'"
        )
        
        def _upload():
            blob_client = self._get_blob_client(dest_blob_path, container_name=target_container)
            
            # Auto-detect content type if not provided
            detected_content_type = content_type
            if not detected_content_type:
                import mimetypes
                detected_content_type, _ = mimetypes.guess_type(local_path)
                if not detected_content_type:
                    detected_content_type = 'application/octet-stream'
            
            # Upload file
            with open(local_path, 'rb') as f:
                blob_client.upload_blob(
                    data=f,
                    overwrite=overwrite,
                    content_settings=ContentSettings(content_type=detected_content_type),
                    timeout=timeout
                )
            
            # Get blob properties
            properties = blob_client.get_blob_properties()
            
            return {
                'blob_url': self.resolve_blob_url(dest_blob_path, container_name=target_container),
                'blob_path': dest_blob_path,
                'etag': properties.etag,
                'size_bytes': local_path_obj.stat().st_size,
                'content_type': detected_content_type,
            }
        
        try:
            result = self._retry_on_transient_failure(_upload)
            logger.info(
                f"Successfully uploaded file '{local_path}' "
                f"({result['size_bytes']} bytes) to blob '{dest_blob_path}'"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to upload file '{local_path}': {e}", exc_info=True)
            raise BlobStorageError(f"Failed to upload file: {e}") from e
    
    def exists(self, blob_path_or_url: str, container_name: Optional[str] = None) -> bool:
        """
        Check if blob exists.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            container_name: Optional container name override (if None, uses instance container_name)
            
        Returns:
            True if blob exists, False if not found (404)
            
        Raises:
            BlobStorageError: For other errors (not 404)
        """
        logger.debug(f"Checking if blob exists: '{blob_path_or_url}'")
        
        def _check_exists():
            blob_client = self._get_blob_client(blob_path_or_url, container_name=container_name)
            try:
                blob_client.get_blob_properties()
                return True
            except ResourceNotFoundError:
                return False
        
        try:
            result = self._retry_on_transient_failure(_check_exists)
            logger.debug(f"Blob '{blob_path_or_url}' exists: {result}")
            return result
        except Exception as e:
            logger.error(f"Error checking blob existence '{blob_path_or_url}': {e}", exc_info=True)
            raise BlobStorageError(f"Error checking blob existence: {e}") from e
    
    def get_properties(self, blob_path_or_url: str, container_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get blob properties.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            container_name: Optional container name override (if None, uses instance container_name)
            
        Returns:
            Dict with properties:
                - etag: Blob ETag
                - size_bytes: File size in bytes
                - content_type: Content type
                - last_modified: Last modified timestamp
        """
        logger.debug(f"Getting properties for blob: '{blob_path_or_url}'")
        
        def _get_props():
            blob_client = self._get_blob_client(blob_path_or_url, container_name=container_name)
            properties = blob_client.get_blob_properties()
            
            return {
                'etag': properties.etag,
                'size_bytes': properties.size,
                'content_type': properties.content_settings.content_type if properties.content_settings else None,
                'last_modified': properties.last_modified.isoformat() if properties.last_modified else None,
            }
        
        try:
            result = self._retry_on_transient_failure(_get_props)
            logger.debug(f"Retrieved properties for blob '{blob_path_or_url}': {result}")
            return result
        except ResourceNotFoundError as e:
            raise BlobStorageError(f"Blob not found: {e}") from e
        except Exception as e:
            logger.error(f"Error getting blob properties '{blob_path_or_url}': {e}", exc_info=True)
            raise BlobStorageError(f"Error getting blob properties: {e}") from e
    
    def delete_blob(self, blob_path_or_url: str, container_name: Optional[str] = None) -> None:
        """
        Delete a blob from storage.
        
        Args:
            blob_path_or_url: Absolute URL or relative blob path
            container_name: Optional container name override (if None, uses instance container_name)
            
        Raises:
            BlobStorageError: If deletion fails
        """
        logger.info(f"Deleting blob: '{blob_path_or_url}'")
        
        def _delete():
            blob_client = self._get_blob_client(blob_path_or_url, container_name=container_name)
            blob_client.delete_blob()
        
        try:
            self._retry_on_transient_failure(_delete)
            logger.info(f"Successfully deleted blob: '{blob_path_or_url}'")
        except ResourceNotFoundError:
            # Blob doesn't exist - that's okay, consider it already deleted
            logger.warning(f"Blob not found (may already be deleted): '{blob_path_or_url}'")
            raise BlobStorageError(f"Blob not found: {blob_path_or_url}")
        except Exception as e:
            logger.error(f"Failed to delete blob '{blob_path_or_url}': {e}", exc_info=True)
            raise BlobStorageError(f"Failed to delete blob: {e}") from e

