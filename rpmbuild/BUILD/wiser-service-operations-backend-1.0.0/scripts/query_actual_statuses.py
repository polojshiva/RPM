#!/usr/bin/env python3
"""
Query actual status values from database to understand what's really stored
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

db = SessionLocal()

try:
    # Query distinct detailed_status values
    print("=" * 60)
    print("DETAILED STATUS VALUES (from packet.detailed_status):")
    print("=" * 60)
    result = db.execute(text("""
        SELECT detailed_status, COUNT(*) as count
        FROM service_ops.packet
        GROUP BY detailed_status
        ORDER BY count DESC, detailed_status
    """))
    for row in result:
        print(f"  {row[0]}: {row[1]} packets")
    
    # Query distinct validation_status values
    print("\n" + "=" * 60)
    print("VALIDATION STATUS VALUES (from packet.validation_status):")
    print("=" * 60)
    result = db.execute(text("""
        SELECT validation_status, COUNT(*) as count
        FROM service_ops.packet
        GROUP BY validation_status
        ORDER BY count DESC, validation_status
    """))
    for row in result:
        print(f"  {row[0]}: {row[1]} packets")
    
    # Query distinct operational_decision values
    print("\n" + "=" * 60)
    print("OPERATIONAL DECISION VALUES (from packet_decision.operational_decision):")
    print("=" * 60)
    result = db.execute(text("""
        SELECT operational_decision, COUNT(*) as count
        FROM service_ops.packet_decision
        WHERE is_active = true
        GROUP BY operational_decision
        ORDER BY count DESC, operational_decision
    """))
    for row in result:
        print(f"  {row[0]}: {row[1]} decisions")
    
    # Query distinct clinical_decision values
    print("\n" + "=" * 60)
    print("CLINICAL DECISION VALUES (from packet_decision.clinical_decision):")
    print("=" * 60)
    result = db.execute(text("""
        SELECT clinical_decision, COUNT(*) as count
        FROM service_ops.packet_decision
        WHERE is_active = true
        GROUP BY clinical_decision
        ORDER BY count DESC, clinical_decision
    """))
    for row in result:
        print(f"  {row[0]}: {row[1]} decisions")
    
    print("\n" + "=" * 60)
    
finally:
    db.close()
