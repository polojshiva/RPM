"""
Reset Packets to Initial State
Removes approve/dismissal decisions and resets packet status back to initial state
Keeps packets and documents, just resets their workflow status
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.services.db import engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def reset_packets_to_initial_state():
    """
    Reset all packets to their initial state:
    - Delete packet_decision records (approve/dismissal decisions)
    - Reset packet status fields to initial state:
      * detailed_status = NULL (back to "New")
      * assigned_to = NULL
      * validation_complete = False
      * closed_date = NULL
    - Keep packets and documents intact
    """
    logger.info("=" * 80)
    logger.info("RESETTING PACKETS TO INITIAL STATE")
    logger.info("=" * 80)
    
    try:
        with engine.connect() as conn:
            # Step 1: Delete all decision records
            logger.info("\n1. Deleting approve/dismissal decision records...")
            
            delete_decisions_sql = """
            BEGIN;
            
            -- Delete all packet_decision records (approve/dismissal decisions)
            DELETE FROM service_ops.packet_decision;
            
            COMMIT;
            """
            
            result = conn.execute(text(delete_decisions_sql))
            conn.commit()
            
            logger.info("  ✓ Deleted all packet_decision records")
            
            # Step 2: Reset packet status fields to initial state
            logger.info("\n2. Resetting packet status fields to initial state...")
            
            reset_packets_sql = """
            BEGIN;
            
            -- Reset all packets to initial state
            UPDATE service_ops.packet
            SET 
                detailed_status = NULL,           -- Back to "New" (not in workflow)
                assigned_to = NULL,                -- No assignment
                validation_complete = False,      -- Validation not complete
                clinical_review_complete = False,  -- Clinical review not complete
                delivery_complete = False,         -- Delivery not complete
                closed_date = NULL,               -- Not closed
                letter_delivered = NULL,          -- Letter not delivered
                updated_at = NOW()
            WHERE detailed_status IS NOT NULL      -- Only update packets that have been processed
               OR assigned_to IS NOT NULL
               OR validation_complete = True
               OR clinical_review_complete = True
               OR delivery_complete = True
               OR closed_date IS NOT NULL
               OR letter_delivered IS NOT NULL;
            
            COMMIT;
            """
            
            result = conn.execute(text(reset_packets_sql))
            conn.commit()
            
            updated_count = result.rowcount
            logger.info(f"  ✓ Reset {updated_count} packet(s) to initial state")
            
            # Step 3: Verify reset
            logger.info("\n3. Verifying reset...")
            
            # Check decision records
            result = conn.execute(text("SELECT COUNT(*) FROM service_ops.packet_decision"))
            decision_count = result.scalar()
            if decision_count == 0:
                logger.info(f"  ✓ packet_decision: {decision_count} records (all deleted)")
            else:
                logger.warning(f"  ⚠ packet_decision: {decision_count} records (expected 0)")
            
            # Check packet status
            result = conn.execute(text("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN detailed_status IS NULL THEN 1 END) as null_status,
                    COUNT(CASE WHEN assigned_to IS NULL THEN 1 END) as unassigned,
                    COUNT(CASE WHEN validation_complete = False THEN 1 END) as validation_not_complete,
                    COUNT(CASE WHEN closed_date IS NULL THEN 1 END) as not_closed
                FROM service_ops.packet
            """))
            
            stats = result.fetchone()
            total = stats[0]
            null_status = stats[1]
            unassigned = stats[2]
            validation_not_complete = stats[3]
            not_closed = stats[4]
            
            logger.info(f"\n  Packet Status Summary:")
            logger.info(f"    Total packets: {total}")
            logger.info(f"    NULL detailed_status (New): {null_status}/{total}")
            logger.info(f"    Unassigned: {unassigned}/{total}")
            logger.info(f"    Validation not complete: {validation_not_complete}/{total}")
            logger.info(f"    Not closed: {not_closed}/{total}")
            
            # Check if all packets are in initial state
            if null_status == total and unassigned == total and validation_not_complete == total:
                logger.info("\n  ✓ All packets are in initial state")
            else:
                logger.warning("\n  ⚠ Some packets may not be fully reset")
            
            # Show packets that still have status
            result = conn.execute(text("""
                SELECT 
                    external_id,
                    detailed_status,
                    assigned_to,
                    validation_complete,
                    closed_date
                FROM service_ops.packet
                WHERE detailed_status IS NOT NULL
                   OR assigned_to IS NOT NULL
                   OR validation_complete = True
                   OR closed_date IS NOT NULL
                ORDER BY external_id
            """))
            
            remaining = result.fetchall()
            if remaining:
                logger.warning(f"\n  ⚠ Found {len(remaining)} packet(s) that still have status:")
                for row in remaining:
                    logger.warning(f"    {row[0]}: status={row[1]}, assigned={row[2]}, validation={row[3]}, closed={row[4]}")
            else:
                logger.info("\n  ✓ All packets are in initial state (NULL status, unassigned)")
            
            logger.info("\n" + "=" * 80)
            logger.info("✓ RESET COMPLETE")
            logger.info("=" * 80)
            logger.info("\nSummary:")
            logger.info(f"  - Deleted all decision record(s)")
            logger.info(f"  - Reset {updated_count} packet(s) to initial state")
            logger.info(f"  - Packets are now in 'New' state (detailed_status = NULL)")
            logger.info(f"  - Packets are unassigned (assigned_to = NULL)")
            logger.info(f"  - Validation phase reset (validation_complete = False)")
            logger.info("\nPackets are ready for testing again:")
            logger.info("  - Click 'Validate' to start Intake Validation")
            logger.info("  - Packets will appear in 'Total Packets' but not in 'Intake Validation' count")
            logger.info("  - All approve/dismissal decisions have been removed\n")
            
            return True
            
    except Exception as e:
        logger.error(f"✗ Reset failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = reset_packets_to_initial_state()
    sys.exit(0 if success else 1)






