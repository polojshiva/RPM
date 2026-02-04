#!/usr/bin/env python3
"""
Add UTN values to some existing packets for testing the UTN filter.

This script:
1. Finds existing packets (recent ones)
2. Gets or creates their packet_decision records
3. Updates some with UTN values and leaves some without UTN
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, func
from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.document_db import PacketDocumentDB
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_utn(index: int) -> str:
    """Generate a realistic UTN format: JLB + 11 digits"""
    # Format: JLB + 11 digits (e.g., JLB86260080030)
    base_number = 86260080000 + index
    return f"JLB{base_number:011d}"


def add_utn_to_packets():
    """Add UTN values to some existing packets"""
    db = SessionLocal()
    try:
        # Find recent packets (last 50, ordered by received_date desc)
        packets = db.query(PacketDB).order_by(PacketDB.received_date.desc()).limit(50).all()
        
        if not packets:
            logger.warning("No packets found in database")
            return
        
        logger.info(f"Found {len(packets)} packets. Updating UTN values...")
        
        updated_with_utn = 0
        updated_without_utn = 0
        skipped = 0
        
        for i, packet in enumerate(packets):
            # Get or create packet_decision
            # First, try to get the active decision
            packet_decision = db.query(PacketDecisionDB).filter(
                PacketDecisionDB.packet_id == packet.packet_id,
                PacketDecisionDB.is_active == True
            ).first()
            
            # If no active decision, get the most recent one
            if not packet_decision:
                packet_decision = db.query(PacketDecisionDB).filter(
                    PacketDecisionDB.packet_id == packet.packet_id
                ).order_by(PacketDecisionDB.created_at.desc()).first()
            
            # If still no decision, we need to create one
            if not packet_decision:
                # Get the packet_document_id (required for packet_decision)
                packet_document = db.query(PacketDocumentDB).filter(
                    PacketDocumentDB.packet_id == packet.packet_id
                ).first()
                
                if not packet_document:
                    logger.warning(f"Packet {packet.external_id} has no document, skipping")
                    skipped += 1
                    continue
                
                # Create a new packet_decision
                packet_decision = PacketDecisionDB(
                    packet_id=packet.packet_id,
                    packet_document_id=packet_document.packet_document_id,
                    decision_type='APPROVE',
                    operational_decision='PENDING',
                    clinical_decision='PENDING',
                    is_active=True,
                    created_at=datetime.now(timezone.utc)
                )
                db.add(packet_decision)
                db.flush()  # Get the ID
                logger.info(f"Created new packet_decision for {packet.external_id}")
            
            # Update UTN: alternate between with UTN and without UTN
            # First 15 packets get UTN, next 15 don't, then repeat
            if i < 15 or (30 <= i < 45):
                # Add UTN
                utn_value = generate_utn(i)
                packet_decision.utn = utn_value
                packet_decision.utn_status = 'SUCCESS'
                packet_decision.utn_received_at = datetime.now(timezone.utc)
                updated_with_utn += 1
                logger.info(f"Added UTN {utn_value} to packet {packet.external_id}")
            else:
                # Ensure no UTN (set to None/null)
                packet_decision.utn = None
                packet_decision.utn_status = 'NONE'
                packet_decision.utn_received_at = None
                updated_without_utn += 1
                logger.info(f"Set UTN to NULL for packet {packet.external_id}")
        
        # Commit all changes
        db.commit()
        
        logger.info("=" * 60)
        logger.info("UTN Update Summary:")
        logger.info(f"  Packets with UTN: {updated_with_utn}")
        logger.info(f"  Packets without UTN: {updated_without_utn}")
        logger.info(f"  Skipped (no document): {skipped}")
        logger.info("=" * 60)
        logger.info("✅ Successfully updated UTN values!")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating UTN values: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    add_utn_to_packets()
