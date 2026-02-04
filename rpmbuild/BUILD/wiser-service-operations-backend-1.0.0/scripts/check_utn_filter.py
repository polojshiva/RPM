#!/usr/bin/env python3
"""
Check UTN filter status in database
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import and_, or_
from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB

db = SessionLocal()

try:
    # Check active decisions with UTN
    decisions_with_utn = db.query(PacketDecisionDB).filter(
        PacketDecisionDB.utn.isnot(None),
        PacketDecisionDB.utn != '',
        PacketDecisionDB.is_active == True
    ).all()
    
    print(f"Active decisions with UTN: {len(decisions_with_utn)}")
    for d in decisions_with_utn[:5]:
        packet = db.query(PacketDB).filter(PacketDB.packet_id == d.packet_id).first()
        print(f"  Packet {packet.external_id if packet else d.packet_id}: UTN={d.utn}")
    
    # Check packets via join (like the API does)
    packets_with_utn = db.query(PacketDB).join(
        PacketDecisionDB,
        and_(
            PacketDB.packet_id == PacketDecisionDB.packet_id,
            PacketDecisionDB.is_active == True
        )
    ).filter(
        PacketDecisionDB.utn.isnot(None),
        PacketDecisionDB.utn != ''
    ).limit(10).all()
    
    print(f"\nPackets with UTN (via join): {len(packets_with_utn)}")
    for p in packets_with_utn:
        print(f"  {p.external_id}")
    
    # Check packets without UTN
    packets_without_utn = db.query(PacketDB).outerjoin(
        PacketDecisionDB,
        and_(
            PacketDB.packet_id == PacketDecisionDB.packet_id,
            PacketDecisionDB.is_active == True
        )
    ).filter(
        or_(
            PacketDecisionDB.utn.is_(None),
            PacketDecisionDB.utn == '',
            PacketDecisionDB.packet_id.is_(None)  # No decision at all
        )
    ).limit(10).all()
    
    print(f"\nPackets without UTN: {len(packets_without_utn)}")
    for p in packets_without_utn[:5]:
        print(f"  {p.external_id}")
    
    # Check total packets
    total = db.query(PacketDB).count()
    print(f"\nTotal packets: {total}")
    
finally:
    db.close()
