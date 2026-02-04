"""
Path Builder Utility
Builds deterministic blob storage paths for consolidated document processing.

Storage structure (Option A - date-partitioned):
service_ops_processing/
  YYYY/
    MM-DD/
      {decision_tracking_id}/
        packet_{packet_id}.pdf
        packet_{packet_id}_pages/
          packet_{packet_id}_page_0001.pdf
          packet_{packet_id}_page_0002.pdf
          ...
"""
from datetime import datetime, timezone
from typing import NamedTuple


class ConsolidatedPaths(NamedTuple):
    """Paths for consolidated document storage"""
    processing_root_path: str
    consolidated_pdf_blob_path: str
    pages_folder_blob_prefix: str


def build_consolidated_paths(
    decision_tracking_id: str,
    packet_id: int,
    dt_utc: datetime
) -> ConsolidatedPaths:
    """
    Build deterministic blob storage paths for consolidated document processing.
    
    Args:
        decision_tracking_id: Decision tracking ID (UUID string)
        packet_id: Packet ID (integer)
        dt_utc: UTC datetime for date partitioning
        
    Returns:
        ConsolidatedPaths with:
        - processing_root_path: service_ops_processing/YYYY/MM-DD/{decision_tracking_id}
        - consolidated_pdf_blob_path: .../packet_{packet_id}.pdf
        - pages_folder_blob_prefix: .../packet_{packet_id}_pages
        
    Example:
        decision_tracking_id = "978d15a7-9c3b-41de-86f2-7a87d858f57c"
        packet_id = 12345
        dt_utc = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
        
        Returns:
        - processing_root_path: "service_ops_processing/2026/01-02/978d15a7-9c3b-41de-86f2-7a87d858f57c"
        - consolidated_pdf_blob_path: "service_ops_processing/2026/01-02/978d15a7-9c3b-41de-86f2-7a87d858f57c/packet_12345.pdf"
        - pages_folder_blob_prefix: "service_ops_processing/2026/01-02/978d15a7-9c3b-41de-86f2-7a87d858f57c/packet_12345_pages"
    """
    # Extract date components
    year = dt_utc.year
    month = dt_utc.month
    day = dt_utc.day
    
    # Format MM-DD with zero-padding
    month_day = f"{month:02d}-{day:02d}"
    
    # Build processing root path
    processing_root_path = f"service_ops_processing/{year}/{month_day}/{decision_tracking_id}"
    
    # Build consolidated PDF path
    consolidated_pdf_blob_path = f"{processing_root_path}/packet_{packet_id}.pdf"
    
    # Build pages folder prefix
    pages_folder_blob_prefix = f"{processing_root_path}/packet_{packet_id}_pages"
    
    return ConsolidatedPaths(
        processing_root_path=processing_root_path,
        consolidated_pdf_blob_path=consolidated_pdf_blob_path,
        pages_folder_blob_prefix=pages_folder_blob_prefix
    )


def build_page_blob_path(
    pages_folder_blob_prefix: str,
    packet_id: int,
    page_number: int
) -> str:
    """
    Build blob path for a specific page.
    
    Args:
        pages_folder_blob_prefix: Pages folder prefix from build_consolidated_paths()
        packet_id: Packet ID (integer)
        page_number: Page number (1-based)
        
    Returns:
        Blob path: {pages_folder_blob_prefix}/packet_{packet_id}_page_{page_number:04d}.pdf
        
    Example:
        pages_folder_blob_prefix = "service_ops_processing/2026/01-02/{uuid}/packet_12345_pages"
        packet_id = 12345
        page_number = 1
        
        Returns: "service_ops_processing/2026/01-02/{uuid}/packet_12345_pages/packet_12345_page_0001.pdf"
    """
    # Format page number as 4-digit zero-padded
    page_filename = f"packet_{packet_id}_page_{page_number:04d}.pdf"
    
    return f"{pages_folder_blob_prefix}/{page_filename}"

