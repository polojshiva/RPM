"""
Blob Path Helper Utility
Resolves relative blob paths with optional prefix from environment variable.

This utility ensures consistent blob path resolution across all blob storage operations.
If AZURE_STORAGE_BLOB_PREFIX is set, it will be prepended to relative paths.
"""
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


def resolve_blob_path(relative_path: str) -> str:
    """
    Resolve a relative blob path with optional prefix from environment variable.
    
    This function is IDEMPOTENT - calling it multiple times with the same input
    will return the same result. If the path already starts with the prefix,
    it will not be added again.
    
    This function:
    - Strips leading/trailing slashes and whitespace from the prefix
    - Strips leading slashes from relative_path
    - Combines prefix + relative_path if prefix is set AND path doesn't already start with it
    - Ensures no double slashes in the result
    - Returns relative_path unchanged if prefix is not set
    
    Args:
        relative_path: The relative blob path (e.g., "2026/01-06/uuid/packet_123_page_0001.pdf")
                       or already-resolved path (e.g., "service_ops_processing/2026/01-06/...")
        
    Returns:
        Resolved blob path with prefix if configured:
        - If prefix is "service_ops_processing" and relative_path is "2026/01-06/.../page.pdf"
        - Returns: "service_ops_processing/2026/01-06/.../page.pdf"
        - If relative_path already starts with prefix, returns it unchanged (idempotent)
        - If prefix is not set, returns relative_path unchanged
        
    Examples:
        >>> resolve_blob_path("2026/01-06/uuid/page.pdf")
        "2026/01-06/uuid/page.pdf"  # if prefix not set
        
        >>> resolve_blob_path("2026/01-06/uuid/page.pdf")
        "service_ops_processing/2026/01-06/uuid/page.pdf"  # if prefix="service_ops_processing"
        
        >>> resolve_blob_path("service_ops_processing/2026/01-06/uuid/page.pdf")
        "service_ops_processing/2026/01-06/uuid/page.pdf"  # already has prefix, unchanged (idempotent)
        
        >>> resolve_blob_path("/2026/01-06/uuid/page.pdf")
        "service_ops_processing/2026/01-06/uuid/page.pdf"  # leading slash removed
    """
    if not relative_path:
        return relative_path
    
    # Get prefix from settings (sanitized)
    prefix = get_blob_prefix()
    
    # Normalize relative_path: remove leading slashes
    normalized_path = relative_path.lstrip('/')
    
    # If no prefix, return normalized path as-is
    if not prefix:
        return normalized_path
    
    # IDEMPOTENCY CHECK: If path already starts with the prefix, return it unchanged
    # This prevents double-prefix when resolve_blob_path is called multiple times
    if normalized_path.startswith(f"{prefix}/"):
        return normalized_path
    
    # Combine prefix and path, ensuring no double slashes
    # Both prefix and normalized_path are already stripped of leading/trailing slashes
    resolved_path = f"{prefix}/{normalized_path}"
    
    return resolved_path


def get_blob_prefix() -> Optional[str]:
    """
    Get and sanitize the blob prefix from environment variable.
    
    Returns:
        Sanitized prefix (stripped of leading/trailing slashes and whitespace),
        or None if not set or empty after sanitization.
    """
    prefix = getattr(settings, 'azure_storage_blob_prefix', None)
    
    if not prefix:
        return None
    
    # Sanitize: strip leading/trailing slashes and whitespace
    sanitized = prefix.strip().strip('/')
    
    # Return None if empty after sanitization
    if not sanitized:
        return None
    
    return sanitized


def log_blob_access(
    container_name: str,
    resolved_blob_path: str,
    packet_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    page_num: Optional[int] = None
) -> None:
    """
    Log blob access for debugging (non-secret information only).
    
    Args:
        container_name: Container name
        resolved_blob_path: Final resolved blob path (with prefix if applicable)
        packet_id: Optional packet identifier for context
        doc_id: Optional document identifier for context
        page_num: Optional page number for context
    """
    context_parts = []
    if packet_id:
        context_parts.append(f"packet_id={packet_id}")
    if doc_id:
        context_parts.append(f"doc_id={doc_id}")
    if page_num is not None:
        context_parts.append(f"page_num={page_num}")
    
    context_str = ", ".join(context_parts) if context_parts else "N/A"
    
    prefix = get_blob_prefix()
    prefix_info = f" (prefix={prefix})" if prefix else " (no prefix)"
    
    logger.info(
        f"Blob access: container='{container_name}', "
        f"resolved_blob_path='{resolved_blob_path}'{prefix_info}, "
        f"context=[{context_str}]"
    )

