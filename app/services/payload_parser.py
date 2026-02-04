"""
Payload Parser Service
Extracts structured data from integration.send_serviceops.payload JSONB
With strict validation and normalized output contract

BACKWARD COMPATIBILITY:
This parser supports BOTH old and new payload formats:

OLD FORMAT:
- payload.ingest_data.decision_tracking_id
- payload.ingest_data.raw_payload.documents[]
- payload.file_download_data.extraction_path
- payload.message_type

NEW FORMAT:
- payload.decision_tracking_id (root level)
- payload.documents[] (root level, with blobPath)
- payload.submission_metadata (root level)
- payload.message_type (may be missing, defaults to 'ingest_file_package')

URL CONSTRUCTION:
- If blobPath is absolute (starts with http:// or https://) → use as-is
- If blobPath is relative → construct: {STORAGE_URL}/{CONTAINER}/{blobPath}
- If blobPath missing → fallback to old method: {STORAGE_URL}/{CONTAINER}/{extraction_path}/{fileName}

IMPORTANT: This parser constructs URLs pointing to the SOURCE container only.
The SOURCE container is read-only and owned by the Integration layer.
ServiceOps must NEVER upload to the SOURCE container.

All consumers must use document.source_absolute_url from the parser model.
No other code should construct blob URLs manually.
"""
from typing import Dict, List, Any, Optional, Tuple
from pydantic import BaseModel, Field, HttpUrl, field_validator
from urllib.parse import urljoin
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class DocumentModel(BaseModel):
    """Normalized document model with required fields"""
    document_unique_identifier: str = Field(..., description="Unique identifier for the document")
    file_name: str = Field(..., description="Document file name")
    mime_type: str = Field(..., description="MIME type of the document")
    file_size: Optional[int] = Field(None, description="File size in bytes (optional - can be set when file is downloaded)")
    source_absolute_url: str = Field(..., description="Absolute URL to the blob in Azure Storage")
    checksum: Optional[str] = Field(None, description="Optional checksum for the document")
    
    @field_validator('source_absolute_url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate that source_absolute_url starts with http:// or https://"""
        if not v.startswith(('http://', 'https://')):
            raise ValueError(f"source_absolute_url must start with http:// or https://, got: {v[:50]}...")
        return v


class ParsedPayloadModel(BaseModel):
    """Normalized payload output model with strict validation"""
    decision_tracking_id: str = Field(..., description="Decision tracking ID (UUID)")
    unique_id: Optional[str] = Field(None, description="Unique identifier for the message (optional in new format)")
    message_type: str = Field(..., description="Message type, must be 'ingest_file_package'")
    esmd_transaction_id: Optional[str] = Field(None, description="eSMD transaction ID (optional in new format)")
    submission_metadata: Dict[str, Any] = Field(..., description="Submission metadata dictionary")
    documents: List[DocumentModel] = Field(default_factory=list, description="List of documents (can be empty - will create packet with empty document state)")
    checksum: Optional[str] = Field(None, description="Optional checksum for the package")
    blob_storage_path: Optional[str] = Field(None, description="Optional blob storage path for ZIP file")
    extraction_path: Optional[str] = Field(None, description="Extraction path where ZIP was extracted (optional in new format, replaced by blobPath)")
    
    @field_validator('message_type')
    @classmethod
    def validate_message_type(cls, v: str) -> str:
        """Validate that message_type equals 'ingest_file_package'"""
        if v != 'ingest_file_package':
            raise ValueError(f"message_type must be 'ingest_file_package', got: {v}")
        return v


class PayloadParser:
    """Parse and extract data from send_serviceops payload JSONB with strict validation"""
    
    @staticmethod
    def _extract_decision_tracking_id(payload: Dict[str, Any]) -> Optional[str]:
        """
        Extract decision_tracking_id from payload (backward compatible).
        
        NEW FORMAT: payload.decision_tracking_id (root level)
        OLD FORMAT: payload.ingest_data.decision_tracking_id
        """
        if not payload:
            return None
        # Try new format first (root level)
        if 'decision_tracking_id' in payload:
            return payload.get('decision_tracking_id')
        # Fallback to old format
        ingest_data = payload.get('ingest_data', {})
        if isinstance(ingest_data, dict):
            return ingest_data.get('decision_tracking_id')
        return None
    
    @staticmethod
    def _extract_unique_id(payload: Dict[str, Any]) -> Optional[str]:
        """
        Extract unique_id from payload (backward compatible).
        
        NEW FORMAT: Not present (may derive from decision_tracking_id or documents[].documentUniqueIdentifier)
        OLD FORMAT: payload.ingest_data.unique_id
        
        If missing, derives from first document's documentUniqueIdentifier or decision_tracking_id.
        """
        if not payload:
            return None
        # Try old format first
        ingest_data = payload.get('ingest_data', {})
        if isinstance(ingest_data, dict):
            unique_id = ingest_data.get('unique_id')
            if unique_id:
                return unique_id
        # Try to derive from documents (new format)
        documents = payload.get('documents', [])
        if documents and isinstance(documents, list) and len(documents) > 0:
            first_doc = documents[0]
            if isinstance(first_doc, dict):
                doc_id = first_doc.get('documentUniqueIdentifier') or first_doc.get('document_unique_id')
                if doc_id:
                    return str(doc_id)
        # Fallback to decision_tracking_id
        decision_tracking_id = PayloadParser._extract_decision_tracking_id(payload)
        if decision_tracking_id:
            return decision_tracking_id
        return None
    
    @staticmethod
    def _extract_esmd_transaction_id(payload: Dict[str, Any]) -> Optional[str]:
        """
        Extract esMD transaction ID from payload (backward compatible).
        
        NEW FORMAT: May be in submission_metadata or missing
        OLD FORMAT: payload.ingest_data.esmd_transaction_id
        """
        if not payload:
            return None
        # Try old format first
        ingest_data = payload.get('ingest_data', {})
        if isinstance(ingest_data, dict):
            esmd_id = ingest_data.get('esmd_transaction_id')
            if esmd_id:
                return esmd_id
        # Try to extract from submission_metadata (new format)
        submission_metadata = PayloadParser._extract_submission_metadata(payload)
        if isinstance(submission_metadata, dict):
            esmd_id = submission_metadata.get('esmd_transaction_id') or submission_metadata.get('esMDTransactionId')
            if esmd_id:
                return str(esmd_id)
        return None
    
    @staticmethod
    def _extract_message_type(payload: Dict[str, Any]) -> Optional[str]:
        """
        Extract message_type from payload (backward compatible).
        
        NEW FORMAT: payload.message_type (may be missing, defaults to 'ingest_file_package')
        OLD FORMAT: payload.message_type
        
        If missing, infers from payload structure or defaults to 'ingest_file_package'.
        """
        if not payload:
            return None
        message_type = payload.get('message_type')
        if message_type:
            return message_type
        # Infer from structure: if has decision_tracking_id and documents at root, assume ingest_file_package
        if 'decision_tracking_id' in payload and 'documents' in payload:
            return 'ingest_file_package'
        # Fallback: check old format structure
        if 'ingest_data' in payload and 'file_download_data' in payload:
            return 'ingest_file_package'
        return None
    
    @staticmethod
    def _extract_submission_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract submission metadata (backward compatible).
        
        NEW FORMAT: payload.submission_metadata (root level)
        OLD FORMAT: payload.ingest_data.submission_metadata or payload.ingest_data.raw_payload.submissionMetadata
        """
        if not payload:
            return {}
        # Try new format first (root level)
        if 'submission_metadata' in payload:
            metadata = payload.get('submission_metadata')
            if isinstance(metadata, dict):
                return metadata
        # Fallback to old format
        ingest_data = payload.get('ingest_data', {})
        if not isinstance(ingest_data, dict):
            return {}
        submission_metadata = ingest_data.get('submission_metadata', {})
        if isinstance(submission_metadata, dict):
            return submission_metadata
        # Fallback to raw_payload.submissionMetadata
        raw_payload = ingest_data.get('raw_payload', {})
        if isinstance(raw_payload, dict):
            return raw_payload.get('submissionMetadata', {})
        return {}
    
    @staticmethod
    def _extract_raw_documents(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract raw documents array from payload (backward compatible).
        
        NEW FORMAT: payload.documents[] (root level, with blobPath)
        OLD FORMAT: payload.ingest_data.raw_payload.documents[]
        """
        if not payload:
            return []
        # Try new format first (root level)
        if 'documents' in payload:
            documents = payload.get('documents')
            if isinstance(documents, list):
                return documents
        # Fallback to old format
        ingest_data = payload.get('ingest_data', {})
        if not isinstance(ingest_data, dict):
            return []
        raw_payload = ingest_data.get('raw_payload', {})
        if not isinstance(raw_payload, dict):
            return []
        documents = raw_payload.get('documents', [])
        if not isinstance(documents, list):
            return []
        return documents
    
    @staticmethod
    def _extract_extraction_path(payload: Dict[str, Any]) -> Optional[str]:
        """Extract extraction path where ZIP contents were extracted"""
        if not payload:
            return None
        file_download_data = payload.get('file_download_data', {})
        if isinstance(file_download_data, dict):
            return file_download_data.get('extraction_path')
        return None
    
    @staticmethod
    def _extract_blob_storage_path(payload: Dict[str, Any]) -> Optional[str]:
        """Extract blob storage path for the ZIP file"""
        if not payload:
            return None
        file_download_data = payload.get('file_download_data', {})
        if isinstance(file_download_data, dict):
            return file_download_data.get('blob_storage_path')
        return None
    
    @staticmethod
    def _validate_blob_path(blob_path: str, file_name: str) -> None:
        """
        Validate blob_path correctness according to strict rules.
        
        Rules:
        - blob_path must NOT start with "http://" or "https://"
        - blob_path must NOT start with "/"
        - blob_path must NOT contain the SOURCE container name (e.g., "esmd-download") as a prefix/segment
        - blob_path must be non-empty
        - file_name must be non-empty
        
        Args:
            blob_path: Relative blob path (extraction_path/file_name)
            file_name: Document file name
            
        Raises:
            ValueError: If any validation rule fails, with clear error message listing all issues
        """
        errors = []
        
        # Check blob_path is non-empty
        if not blob_path or not blob_path.strip():
            errors.append("blob_path cannot be empty")
        
        # Check file_name is non-empty
        if not file_name or not file_name.strip():
            errors.append("file_name cannot be empty")
        
        if errors:
            # Don't continue with other checks if basic fields are missing
            raise ValueError(f"Blob path validation failed: {', '.join(errors)}")
        
        blob_path = blob_path.strip()
        
        # Check blob_path does NOT start with "http://" or "https://"
        if blob_path.startswith(('http://', 'https://')):
            errors.append("blob_path must not start with 'http://' or 'https://' (absolute URLs not allowed in payload)")
        
        # Check blob_path does NOT start with "/"
        if blob_path.startswith('/'):
            errors.append("blob_path must not start with '/' (leading slash not allowed)")
        
        # Check blob_path does NOT contain SOURCE container name
        source_container = settings.azure_storage_source_container or settings.container_name
        if source_container:
            container_lower = source_container.lower().strip('/')
            blob_path_lower = blob_path.lower()
            # Check if container name appears as a prefix or segment
            if blob_path_lower.startswith(f"{container_lower}/") or f"/{container_lower}/" in blob_path_lower:
                errors.append(f"blob_path must not contain SOURCE container name '{source_container}' (container name should not be in payload)")
        
        if errors:
            raise ValueError(f"Blob path validation failed: {', '.join(errors)}")
    
    @staticmethod
    def _extract_container_from_blob_path(blob_path: str) -> Optional[Tuple[str, str]]:
        """
        Extract container name from blob path if it starts with a known container.
        
        Known containers:
        - integration-inbound-fax (Fax files)
        - esmd-download (ESMD files)
        
        Returns:
            (container_name, remaining_path) if container detected, None otherwise
        """
        if not blob_path:
            return None
        
        known_containers = [
            'integration-inbound-fax',
            'esmd-download',
        ]
        
        blob_path_normalized = blob_path.strip().lstrip('/')
        for container in known_containers:
            container_normalized = container.strip('/')
            if blob_path_normalized.lower().startswith(f"{container_normalized.lower()}/"):
                remaining_path = blob_path_normalized[len(container_normalized):].lstrip('/')
                return (container, remaining_path)
        
        return None
    
    @staticmethod
    def _construct_source_absolute_url(
        extraction_path: Optional[str], 
        file_name: str, 
        relative_path: Optional[str] = None,
        blob_path: Optional[str] = None
    ) -> str:
        """
        Construct absolute URL to blob in Azure Storage (backward compatible).
        
        Supports both old format (extraction_path + fileName) and new format (blobPath).
        blobPath can be absolute URL (use as-is) or relative path (construct).
        
        If blobPath contains a container name prefix (e.g., "integration-inbound-fax/..."),
        extracts the container and uses it instead of the environment variable.
        
        Args:
            extraction_path: Optional relative path where file was extracted (OLD FORMAT)
            file_name: Required document file name
            relative_path: Optional explicit relative path from payload (OLD FORMAT, takes precedence over extraction_path)
            blob_path: Optional blobPath from new format (NEW FORMAT, takes highest precedence)
            
        Returns:
            Absolute URL: https://{storage_account}.blob.core.windows.net/{container}/{blob_path}
            OR: blob_path if it's already an absolute URL
            
        Raises:
            ValueError: If storage environment variables are missing or if required fields are empty
        """
        # NEW FORMAT: If blob_path is provided and is absolute URL, use as-is
        if blob_path and blob_path.strip():
            blob_path = blob_path.strip()
            if blob_path.startswith(('http://', 'https://')):
                # Already absolute URL, return as-is
                return blob_path
            # blob_path is relative, will construct below
        
        # OLD FORMAT or NEW FORMAT with relative blob_path: construct URL
        storage_account_url = settings.storage_account_url
        # Use SOURCE container (read-only, owned by Integration layer) - default fallback
        container_name = settings.azure_storage_source_container or settings.container_name  # Fallback to legacy for backward compat
        
        # Validate environment variables are configured
        if not storage_account_url or not storage_account_url.strip():
            raise ValueError(
                "AZURE_STORAGE_ACCOUNT_URL (or STORAGE_ACCOUNT_URL) environment variable must be set "
                "to construct source_absolute_url"
            )
        
        # Determine blob_path to use (priority: blob_path > relative_path > extraction_path + file_name)
        if blob_path and blob_path.strip() and not blob_path.startswith(('http://', 'https://')):
            # NEW FORMAT: Use blob_path (relative)
            # Try to extract container from path prefix (e.g., "integration-inbound-fax/...")
            container_result = PayloadParser._extract_container_from_blob_path(blob_path)
            if container_result:
                container_from_path, remaining_path = container_result
                container_name = container_from_path  # Use container from path
                final_blob_path = remaining_path  # Strip container from path
                logger.info(
                    f"Extracted container '{container_from_path}' from blobPath. "
                    f"Remaining path: '{remaining_path}'"
                )
            else:
                # No container in path, use env var container
                final_blob_path = blob_path.strip().lstrip('/')
            # Skip validation for new format blob_path (may contain container name, etc.)
        elif relative_path and relative_path.strip():
            # OLD FORMAT: Use explicit relative_path
            final_blob_path = relative_path.strip().lstrip('/')
            PayloadParser._validate_blob_path(final_blob_path, file_name or "unknown")
        else:
            # OLD FORMAT: Construct from extraction_path + file_name
            if not extraction_path or not extraction_path.strip():
                raise ValueError(
                    "Cannot construct source_absolute_url: "
                    "blobPath (new format) or extraction_path (old format) is required"
                )
            if not file_name or not file_name.strip():
                raise ValueError("file_name cannot be empty (required to construct source_absolute_url)")
            
            # Build relative path: extraction_path/file_name
            # Remove leading/trailing slashes and normalize
            extraction_path = extraction_path.strip('/')
            file_name = file_name.lstrip('/')
            final_blob_path = f"{extraction_path}/{file_name}"
            PayloadParser._validate_blob_path(final_blob_path, file_name)
        
        # Validate container_name is set (either from path extraction or env var)
        if not container_name or not container_name.strip():
            raise ValueError(
                "Container name is required. Either: "
                "1) blobPath must contain container name prefix (e.g., 'integration-inbound-fax/...'), OR "
                "2) AZURE_STORAGE_SOURCE_CONTAINER environment variable must be set. "
                "This is the SOURCE container (read-only) for downloading original documents."
            )
        
        # Construct absolute URL
        base_url = storage_account_url.rstrip('/')
        container = container_name.strip('/')
        absolute_url = f"{base_url}/{container}/{final_blob_path}"
        
        return absolute_url
    
    @staticmethod
    def _normalize_documents(
        raw_documents: List[Dict[str, Any]],
        extraction_path: Optional[str]
    ) -> List[DocumentModel]:
        """
        Normalize raw documents to DocumentModel with source_absolute_url (backward compatible).
        
        Args:
            raw_documents: List of raw document dictionaries from payload
            extraction_path: Optional extraction path for constructing blob URLs (OLD FORMAT)
            
        Returns:
            List of normalized DocumentModel instances
            
        Raises:
            ValueError: If text files (mimeType: text/plain) are found (not supported in v1)
        """
        normalized = []
        for doc in raw_documents:
            if not isinstance(doc, dict):
                continue
            
            # Extract required fields
            # Map DBA naming (document_unique_id) to internal naming (document_unique_identifier)
            document_unique_identifier = (
                doc.get('document_unique_id') or  # DBA naming (preferred)
                doc.get('documentUniqueIdentifier') or  # NEW FORMAT camelCase
                doc.get('document_unique_identifier', '')  # Legacy snake_case
            )
            file_name = doc.get('fileName') or doc.get('file_name', '')
            mime_type = doc.get('mimeType') or doc.get('mime_type', '')
            # file_size is optional - use None if not provided (will be set when file is downloaded)
            file_size = doc.get('fileSize') or doc.get('file_size')
            if file_size == 0:  # Treat 0 as None (unknown size)
                file_size = None
            checksum = doc.get('checksum') or doc.get('Checksum')
            
            # Text files will be automatically converted to PDF by PDFMerger
            # No need to reject them here - let the conversion happen during merge
            # PDFMerger._convert_text_to_pdf() handles text/plain files
            
            # Validate file_name does not start with / (before constructing blob_path)
            if file_name and file_name.strip().startswith('/'):
                raise ValueError(
                    f"file_name must not start with '/' (leading slash not allowed). "
                    f"Got: {file_name[:50]}"
                )
            
            # NEW FORMAT: Extract blobPath (can be absolute URL or relative path)
            blob_path = doc.get('blobPath') or doc.get('blob_path') or None
            
            # OLD FORMAT: Prefer explicit relative_path from payload if available
            relative_path = doc.get('relative_path') or doc.get('relativePath') or None
            
            # Construct source_absolute_url (priority: blob_path > relative_path > extraction_path + file_name)
            source_absolute_url = PayloadParser._construct_source_absolute_url(
                extraction_path, 
                file_name, 
                relative_path=relative_path,
                blob_path=blob_path
            )
            
            normalized.append(DocumentModel(
                document_unique_identifier=document_unique_identifier,
                file_name=file_name,
                mime_type=mime_type,
                file_size=file_size,
                source_absolute_url=source_absolute_url,
                checksum=checksum
            ))
        
        return normalized
    
    @staticmethod
    def _collect_missing_fields(payload: Dict[str, Any]) -> List[str]:
        """
        Collect all missing required fields from payload
        
        Returns:
            List of missing field names (e.g., ['decision_tracking_id', 'documents[0].source_absolute_url'])
        """
        missing = []
        
        # Check top-level fields
        decision_tracking_id = PayloadParser._extract_decision_tracking_id(payload)
        if not decision_tracking_id:
            missing.append('decision_tracking_id')
        
        # unique_id is optional in new format (derived if missing)
        unique_id = PayloadParser._extract_unique_id(payload)
        # Don't require unique_id (can be derived)
        
        # esmd_transaction_id is optional in new format
        esmd_transaction_id = PayloadParser._extract_esmd_transaction_id(payload)
        # Don't require esmd_transaction_id (optional)
        
        message_type = PayloadParser._extract_message_type(payload)
        if not message_type:
            # Try to infer or default
            message_type = 'ingest_file_package'  # Default for backward compatibility
        elif message_type != 'ingest_file_package':
            missing.append(f"message_type (must be 'ingest_file_package', got '{message_type}')")
        
        submission_metadata = PayloadParser._extract_submission_metadata(payload)
        if not submission_metadata:
            missing.append('submission_metadata')
        
        # Check documents
        raw_documents = PayloadParser._extract_raw_documents(payload)
        # Allow empty documents array - will be handled gracefully in document processor
        # Only require that the field exists (can be empty array)
        if raw_documents is None:
            missing.append('documents (field must exist, but can be empty array)')
        elif raw_documents:  # Only validate document fields if array is not empty
            # Check each document's required fields
            for idx, doc in enumerate(raw_documents):
                if not isinstance(doc, dict):
                    missing.append(f'documents[{idx}] (must be a dictionary)')
                    continue
                
                # Check for document_unique_id (DBA naming) or legacy variants
                document_unique_identifier = (
                    doc.get('document_unique_id') or  # DBA naming (preferred)
                    doc.get('documentUniqueIdentifier') or  # Legacy camelCase
                    doc.get('document_unique_identifier')  # Legacy snake_case
                )
                if not document_unique_identifier:
                    missing.append(f'documents[{idx}].document_unique_id (or documentUniqueIdentifier/document_unique_identifier)')
                
                file_name = doc.get('fileName') or doc.get('file_name')
                if not file_name:
                    missing.append(f'documents[{idx}].file_name')
                
                mime_type = doc.get('mimeType') or doc.get('mime_type')
                if not mime_type:
                    missing.append(f'documents[{idx}].mime_type')
                
                # file_size is optional - will be set when file is downloaded if not provided
                # No validation check needed here
                
                # source_absolute_url will be constructed, but we need blobPath (new) or extraction_path (old) or file_name
                blob_path = doc.get('blobPath') or doc.get('blob_path')
                extraction_path = PayloadParser._extract_extraction_path(payload)
                if not blob_path and not extraction_path and not file_name:
                    missing.append(
                        f'documents[{idx}].source_absolute_url (cannot construct without blobPath (new format), '
                        f'extraction_path (old format), or file_name)'
                    )
        
        return missing
    
    @staticmethod
    def parse_full_payload(payload: Dict[str, Any]) -> ParsedPayloadModel:
        """
        Parse entire payload and return normalized, validated output
        
        Args:
            payload: Raw payload dictionary from integration.send_serviceops
            
        Returns:
            ParsedPayloadModel with all required fields validated
            
        Raises:
            ValueError: If any required fields are missing or invalid
        """
        if not payload:
            raise ValueError("Payload cannot be empty")
        
        # Collect all missing fields
        missing_fields = PayloadParser._collect_missing_fields(payload)
        if missing_fields:
            raise ValueError(f"Missing fields: {', '.join(missing_fields)}")
        
        # Extract all fields
        decision_tracking_id = PayloadParser._extract_decision_tracking_id(payload)
        unique_id = PayloadParser._extract_unique_id(payload)
        esmd_transaction_id = PayloadParser._extract_esmd_transaction_id(payload)
        message_type = PayloadParser._extract_message_type(payload)
        submission_metadata = PayloadParser._extract_submission_metadata(payload)
        raw_documents = PayloadParser._extract_raw_documents(payload)
        extraction_path = PayloadParser._extract_extraction_path(payload)
        blob_storage_path = PayloadParser._extract_blob_storage_path(payload)
        
        # Validate we have enough info to construct URLs (either extraction_path OR blobPath in documents)
        # extraction_path is optional in new format (replaced by blobPath)
        # Skip this validation if documents array is empty (will be handled gracefully)
        if raw_documents and len(raw_documents) > 0:
            if not extraction_path or not extraction_path.strip():
                # Check if new format has blobPath in documents
                has_blob_path = False
                for doc in raw_documents:
                    if isinstance(doc, dict):
                        blob_path = doc.get('blobPath') or doc.get('blob_path')
                        if blob_path:
                            has_blob_path = True
                            break
                if not has_blob_path:
                    raise ValueError(
                        "Cannot construct source_absolute_url: "
                        "Either extraction_path (old format) or documents[].blobPath (new format) is required"
                    )
        
        # Validate storage environment variables are configured
        storage_account_url = settings.storage_account_url
        # Use SOURCE container (read-only, owned by Integration layer)
        container_name = settings.azure_storage_source_container or settings.container_name  # Fallback to legacy for backward compat
        if not storage_account_url or not storage_account_url.strip():
            raise ValueError(
                "AZURE_STORAGE_ACCOUNT_URL (or STORAGE_ACCOUNT_URL) environment variable must be set "
                "to construct source_absolute_url"
            )
        if not container_name or not container_name.strip():
            raise ValueError(
                "AZURE_STORAGE_SOURCE_CONTAINER (or AZURE_STORAGE_CONTAINER_NAME for backward compatibility) "
                "environment variable must be set to construct source_absolute_url. "
                "This is the SOURCE container (read-only) for downloading original documents."
            )
        
        # Normalize documents with source_absolute_url (constructed from env vars + relative paths)
        documents = PayloadParser._normalize_documents(raw_documents, extraction_path)
        
        # Allow empty documents array - will be handled gracefully in document processor
        # Empty documents will create packet with empty document state
        # Only raise error if documents is None (not provided), not if it's an empty array
        if documents is None:
            raise ValueError("documents field must exist (can be empty array)")
        
        # Validate each document's source_absolute_url starts with http (only if documents exist)
        for idx, doc in enumerate(documents):
            if not doc.source_absolute_url.startswith(('http://', 'https://')):
                raise ValueError(
                    f"documents[{idx}].source_absolute_url must start with http:// or https://, "
                    f"got: {doc.source_absolute_url[:50]}..."
                )
        
        # Extract optional checksum (from file_download_data or top-level)
        checksum = None
        file_download_data = payload.get('file_download_data', {})
        if isinstance(file_download_data, dict):
            checksum = file_download_data.get('checksum')
        if not checksum:
            checksum = payload.get('checksum')
        
        # Ensure message_type defaults to 'ingest_file_package' if missing
        if not message_type:
            message_type = 'ingest_file_package'
        
        # Ensure unique_id is derived if missing
        if not unique_id:
            unique_id = decision_tracking_id  # Fallback to decision_tracking_id
        
        # Create and return normalized model (Pydantic will validate)
        return ParsedPayloadModel(
            decision_tracking_id=decision_tracking_id,
            unique_id=unique_id,
            message_type=message_type,
            esmd_transaction_id=esmd_transaction_id,
            submission_metadata=submission_metadata,
            documents=documents,
            checksum=checksum,
            blob_storage_path=blob_storage_path,
            extraction_path=extraction_path
        )
