"""Check packet counts in database"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Get total count
    result = conn.execute(text("SELECT COUNT(*) as total FROM service_ops.packet"))
    total = result.scalar()
    print(f"Total packets: {total}")
    
    # Get packets with their status
    result = conn.execute(text("""
        SELECT external_id, detailed_status 
        FROM service_ops.packet 
        ORDER BY external_id
    """))
    rows = result.fetchall()
    print("\nPackets in database:")
    for row in rows:
        status = row[1] if row[1] else "New (NULL)"
        print(f"  {row[0]}: {status}")
    
    # Get status breakdown
    result = conn.execute(text("""
        SELECT 
            COUNT(CASE WHEN detailed_status IS NULL THEN 1 END) as new_count,
            COUNT(CASE WHEN detailed_status = 'Intake Validation' THEN 1 END) as intake_validation,
            COUNT(CASE WHEN detailed_status = 'Clinical Review' THEN 1 END) as clinical_review,
            COUNT(CASE WHEN detailed_status = 'Closed - Delivered' THEN 1 END) as closed_delivered,
            COUNT(CASE WHEN detailed_status = 'Closed - Dismissed' THEN 1 END) as closed_dismissed
        FROM service_ops.packet
    """))
    stats = result.fetchone()
    print("\nStatus breakdown:")
    print(f"  New (NULL): {stats[0]}")
    print(f"  Intake Validation: {stats[1]}")
    print(f"  Clinical Review: {stats[2]}")
    print(f"  Closed - Delivered: {stats[3]}")
    print(f"  Closed - Dismissed: {stats[4]}")
    print(f"\nSum of statuses: {stats[0] + stats[1] + stats[2] + stats[3] + stats[4]}")






