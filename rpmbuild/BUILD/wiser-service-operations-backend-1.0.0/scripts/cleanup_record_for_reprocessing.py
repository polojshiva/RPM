"""
Cleanup Script for Reprocessing a Single Record

This script cleans all database records and blob storage files for a specific
decision_tracking_id to allow clean reprocessing from scratch.

Usage:
    python scripts/cleanup_record_for_reprocessing.py <decision_tracking_id>

Example:
    python scripts/cleanup_record_for_reprocessing.py 550e8400-e29b-41d4-a716-446655440000
"""
import sys
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
from app.services.blob_storage import BlobStorageClient, BlobStorageError
from app.config import settings
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_packet_info(decision_tracking_id: str) -> Optional[Dict[str, Any]]:
    """Get packet information before deletion (for blob storage cleanup)"""
    logger.info(f"Fetching packet information for decision_tracking_id: {decision_tracking_id}")
    
    query = text("""
        SELECT 
            p.packet_id,
            p.decision_tracking_id,
            p.external_id as packet_external_id,
            p.received_date,
            pd.packet_document_id,
            pd.external_id as document_external_id,
            pd.consolidated_blob_path,
            pd.pages_metadata,
            pd.split_status,
            pd.ocr_status
        FROM service_ops.packet p
        LEFT JOIN service_ops.packet_document pd ON p.packet_id = pd.packet_id
        WHERE p.decision_tracking_id = :decision_tracking_id
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"decision_tracking_id": decision_tracking_id})
        row = result.fetchone()
        
        if row is None:
            logger.warning(f"No packet found for decision_tracking_id: {decision_tracking_id}")
            return None
        
        return {
            "packet_id": row[0],
            "decision_tracking_id": row[1],
            "packet_external_id": row[2],
            "received_date": row[3],
            "packet_document_id": row[4],
            "document_external_id": row[5],
            "consolidated_blob_path": row[6],
            "pages_metadata": row[7],
            "split_status": row[8],
            "ocr_status": row[9],
        }


def extract_page_blob_paths(pages_metadata: Optional[Dict]) -> List[str]:
    """Extract blob paths from pages_metadata JSONB"""
    if not pages_metadata:
        return []
    
    page_paths = []
    pages = pages_metadata.get("pages", [])
    
    for page in pages:
        blob_path = page.get("blob_path")
        if blob_path:
            page_paths.append(blob_path)
    
    return page_paths


def delete_blob_storage_files(
    decision_tracking_id: str,
    consolidated_blob_path: Optional[str],
    pages_metadata: Optional[Dict],
    dry_run: bool = False
) -> Dict[str, Any]:
    """Delete blob storage files (consolidated PDF and page PDFs)"""
    logger.info("=" * 80)
    logger.info("BLOB STORAGE CLEANUP")
    logger.info("=" * 80)
    
    deleted_files = []
    errors = []
    
    # Initialize blob client for DEST container
    dest_container = settings.azure_storage_dest_container
    if not dest_container:
        logger.error("azure_storage_dest_container not configured")
        return {"deleted": deleted_files, "errors": ["Container not configured"]}
    
    blob_client = BlobStorageClient(container_name=dest_container)
    
    # Delete consolidated PDF
    if consolidated_blob_path:
        logger.info(f"Deleting consolidated PDF: {consolidated_blob_path}")
        if not dry_run:
            try:
                blob_client.delete_blob(consolidated_blob_path, container_name=dest_container)
                deleted_files.append(consolidated_blob_path)
                logger.info(f"✓ Deleted: {consolidated_blob_path}")
            except BlobStorageError as e:
                error_msg = f"Failed to delete consolidated PDF: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        else:
            logger.info(f"[DRY RUN] Would delete: {consolidated_blob_path}")
            deleted_files.append(consolidated_blob_path)
    else:
        logger.info("No consolidated_blob_path found (may not have been created)")
    
    # Delete page PDFs
    page_paths = extract_page_blob_paths(pages_metadata)
    if page_paths:
        logger.info(f"Found {len(page_paths)} page PDFs to delete")
        for page_path in page_paths:
            logger.info(f"Deleting page PDF: {page_path}")
            if not dry_run:
                try:
                    blob_client.delete_blob(page_path, container_name=dest_container)
                    deleted_files.append(page_path)
                    logger.info(f"✓ Deleted: {page_path}")
                except BlobStorageError as e:
                    error_msg = f"Failed to delete page PDF {page_path}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            else:
                logger.info(f"[DRY RUN] Would delete: {page_path}")
                deleted_files.append(page_path)
    else:
        logger.info("No page PDFs found in pages_metadata (may not have been created)")
    
    # Try to delete entire folder (if using Azure Storage Explorer or CLI)
    # Note: Azure Blob Storage doesn't have folders, but we can list and delete by prefix
    if not dry_run and (consolidated_blob_path or page_paths):
        # Extract folder prefix from consolidated_blob_path or first page path
        folder_prefix = None
        if consolidated_blob_path:
            # Extract folder: service_ops_processing/YYYY/MM-DD/{decision_tracking_id}/
            parts = consolidated_blob_path.split('/')
            if len(parts) >= 4:
                folder_prefix = '/'.join(parts[:-1]) + '/'  # Everything except the filename
        elif page_paths:
            # Extract folder from first page path
            parts = page_paths[0].split('/')
            if len(parts) >= 2:
                folder_prefix = '/'.join(parts[:-1]) + '/'  # Everything except the filename
        
        if folder_prefix:
            logger.info(f"Attempting to delete remaining blobs in folder: {folder_prefix}")
            try:
                # Use Azure SDK directly to list and delete by prefix
                blob_service_client = blob_client._get_blob_service_client()
                container_client = blob_service_client.get_container_client(dest_container)
                
                remaining_blobs = list(container_client.list_blobs(name_starts_with=folder_prefix))
                if remaining_blobs:
                    logger.info(f"Found {len(remaining_blobs)} remaining blobs in folder")
                    for blob in remaining_blobs:
                        try:
                            blob_client.delete_blob(blob.name, container_name=dest_container)
                            deleted_files.append(blob.name)
                            logger.info(f"✓ Deleted remaining blob: {blob.name}")
                        except Exception as e:
                            error_msg = f"Failed to delete remaining blob {blob.name}: {e}"
                            logger.warning(error_msg)
                            errors.append(error_msg)
                else:
                    logger.info("No remaining blobs found in folder")
            except Exception as e:
                logger.warning(f"Could not list/delete remaining blobs by prefix: {e}")
    
    return {
        "deleted": deleted_files,
        "errors": errors,
        "deleted_count": len(deleted_files),
        "error_count": len(errors)
    }


def cleanup_database(decision_tracking_id: str, dry_run: bool = False) -> Dict[str, Any]:
    """Clean all database records for a decision_tracking_id"""
    logger.info("=" * 80)
    logger.info("DATABASE CLEANUP")
    logger.info("=" * 80)
    
    cleanup_sql = text("""
        BEGIN;
        
        -- Delete decisions
        DELETE FROM service_ops.packet_decision 
        WHERE packet_id IN (
            SELECT packet_id FROM service_ops.packet 
            WHERE decision_tracking_id = :decision_tracking_id
        );
        
        -- Delete validation runs
        DELETE FROM service_ops.validation_run 
        WHERE packet_id IN (
            SELECT packet_id FROM service_ops.packet 
            WHERE decision_tracking_id = :decision_tracking_id
        );
        
        -- Delete documents
        DELETE FROM service_ops.packet_document 
        WHERE packet_id IN (
            SELECT packet_id FROM service_ops.packet 
            WHERE decision_tracking_id = :decision_tracking_id
        );
        
        -- Delete packet
        DELETE FROM service_ops.packet 
        WHERE decision_tracking_id = :decision_tracking_id;
        
        -- Delete from inbox
        DELETE FROM service_ops.integration_inbox 
        WHERE decision_tracking_id = :decision_tracking_id;
        
        COMMIT;
    """)
    
    if dry_run:
        logger.info("[DRY RUN] Would execute database cleanup SQL")
        return {"status": "dry_run", "deleted": []}
    
    try:
        with engine.connect() as conn:
            result = conn.execute(cleanup_sql, {"decision_tracking_id": decision_tracking_id})
            conn.commit()
            
            logger.info("✓ Database cleanup completed")
            
            # Verify cleanup
            verify_query = text("""
                SELECT 
                    (SELECT COUNT(*) FROM service_ops.packet WHERE decision_tracking_id = :decision_tracking_id) as packet_count,
                    (SELECT COUNT(*) FROM service_ops.packet_document pd 
                     JOIN service_ops.packet p ON pd.packet_id = p.packet_id 
                     WHERE p.decision_tracking_id = :decision_tracking_id) as document_count,
                    (SELECT COUNT(*) FROM service_ops.integration_inbox WHERE decision_tracking_id = :decision_tracking_id) as inbox_count,
                    (SELECT COUNT(*) FROM service_ops.packet_decision pd 
                     JOIN service_ops.packet p ON pd.packet_id = p.packet_id 
                     WHERE p.decision_tracking_id = :decision_tracking_id) as decision_count,
                    (SELECT COUNT(*) FROM service_ops.validation_run vr 
                     JOIN service_ops.packet p ON vr.packet_id = p.packet_id 
                     WHERE p.decision_tracking_id = :decision_tracking_id) as validation_count
            """)
            
            verify_result = conn.execute(verify_query, {"decision_tracking_id": decision_tracking_id})
            row = verify_result.fetchone()
            
            counts = {
                "packet": row[0],
                "document": row[1],
                "inbox": row[2],
                "decision": row[3],
                "validation": row[4],
            }
            
            all_zero = all(count == 0 for count in counts.values())
            
            if all_zero:
                logger.info("✓ Verification: All records deleted successfully")
            else:
                logger.warning(f"⚠ Verification: Some records may still exist: {counts}")
            
            return {
                "status": "success" if all_zero else "partial",
                "counts": counts
            }
            
    except Exception as e:
        logger.error(f"✗ Database cleanup failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def check_source_table(decision_tracking_id: str) -> Dict[str, Any]:
    """Check status of record in integration.send_serviceops"""
    logger.info("=" * 80)
    logger.info("SOURCE TABLE CHECK")
    logger.info("=" * 80)
    
    query = text("""
        SELECT 
            message_id,
            decision_tracking_id,
            is_deleted,
            created_at,
            channel_type_id,
            CASE 
                WHEN channel_type_id = 1 THEN 'Genzeon Portal'
                WHEN channel_type_id = 2 THEN 'Genzeon Fax'
                WHEN channel_type_id = 3 THEN 'ESMD'
                ELSE 'Unknown'
            END as channel_name
        FROM integration.send_serviceops
        WHERE decision_tracking_id = :decision_tracking_id
        ORDER BY created_at DESC
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"decision_tracking_id": decision_tracking_id})
        rows = result.fetchall()
        
        if not rows:
            logger.warning(f"No record found in integration.send_serviceops for decision_tracking_id: {decision_tracking_id}")
            logger.info("You may need to insert the record manually for reprocessing")
            return {"found": False, "records": []}
        
        records = []
        for row in rows:
            record = {
                "message_id": row[0],
                "decision_tracking_id": row[1],
                "is_deleted": row[2],
                "created_at": str(row[3]),
                "channel_type_id": row[4],
                "channel_name": row[5],
            }
            records.append(record)
            logger.info(f"Found record: message_id={record['message_id']}, is_deleted={record['is_deleted']}, channel={record['channel_name']}")
        
        # Check if any record is ready for processing
        ready_for_processing = any(not r["is_deleted"] for r in records)
        
        if ready_for_processing:
            logger.info("✓ Record is ready for processing (is_deleted=false)")
        else:
            logger.warning("⚠ All records are marked as deleted (is_deleted=true)")
            logger.info("You may need to update is_deleted=false for reprocessing")
        
        return {
            "found": True,
            "records": records,
            "ready_for_processing": ready_for_processing
        }


def main():
    """Main cleanup function"""
    if len(sys.argv) < 2:
        logger.error("Usage: python cleanup_record_for_reprocessing.py <decision_tracking_id> [--dry-run]")
        sys.exit(1)
    
    decision_tracking_id = sys.argv[1]
    dry_run = "--dry-run" in sys.argv or "--dryrun" in sys.argv
    
    logger.info("=" * 80)
    logger.info("RECORD CLEANUP FOR REPROCESSING")
    logger.info("=" * 80)
    logger.info(f"Decision Tracking ID: {decision_tracking_id}")
    logger.info(f"Dry Run: {dry_run}")
    logger.info("")
    
    # Step 1: Get packet info (before deletion)
    packet_info = get_packet_info(decision_tracking_id)
    
    if not packet_info:
        logger.error(f"No packet found for decision_tracking_id: {decision_tracking_id}")
        logger.info("Nothing to clean. Exiting.")
        sys.exit(1)
    
    logger.info(f"Found packet: packet_id={packet_info['packet_id']}, external_id={packet_info['packet_external_id']}")
    logger.info(f"Document: packet_document_id={packet_info['packet_document_id']}, external_id={packet_info['document_external_id']}")
    logger.info(f"Status: split_status={packet_info['split_status']}, ocr_status={packet_info['ocr_status']}")
    logger.info("")
    
    # Step 2: Delete blob storage files
    blob_result = delete_blob_storage_files(
        decision_tracking_id=decision_tracking_id,
        consolidated_blob_path=packet_info.get("consolidated_blob_path"),
        pages_metadata=packet_info.get("pages_metadata"),
        dry_run=dry_run
    )
    
    logger.info(f"Blob cleanup: {blob_result['deleted_count']} files deleted, {blob_result['error_count']} errors")
    logger.info("")
    
    # Step 3: Delete database records
    db_result = cleanup_database(decision_tracking_id, dry_run=dry_run)
    
    logger.info(f"Database cleanup: {db_result.get('status', 'unknown')}")
    if "counts" in db_result:
        logger.info(f"Remaining counts: {db_result['counts']}")
    logger.info("")
    
    # Step 4: Check source table
    source_result = check_source_table(decision_tracking_id)
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("CLEANUP SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Blob Storage: {blob_result['deleted_count']} files deleted")
    logger.info(f"Database: {db_result.get('status', 'unknown')}")
    logger.info(f"Source Table: {'Ready' if source_result.get('ready_for_processing') else 'Not Ready'}")
    
    if dry_run:
        logger.info("")
        logger.info("⚠ DRY RUN MODE - No changes were made")
        logger.info("Run without --dry-run to perform actual cleanup")
    
    if blob_result['error_count'] > 0:
        logger.warning(f"⚠ {blob_result['error_count']} errors occurred during blob cleanup")
        for error in blob_result['errors']:
            logger.warning(f"  - {error}")
    
    if not source_result.get('ready_for_processing'):
        logger.info("")
        logger.info("⚠ To enable reprocessing, update integration.send_serviceops:")
        logger.info(f"   UPDATE integration.send_serviceops")
        logger.info(f"   SET is_deleted = false")
        logger.info(f"   WHERE decision_tracking_id = '{decision_tracking_id}';")
    
    logger.info("")
    logger.info("✓ Cleanup complete! The record is ready for reprocessing.")


if __name__ == "__main__":
    main()

