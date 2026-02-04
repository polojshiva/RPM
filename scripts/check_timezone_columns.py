"""Check timezone column types for watermark tables"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    # Check clinical_ops_poll_watermark
    result1 = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'clinical_ops_poll_watermark' 
        AND column_name = 'last_created_at'
    """)).fetchone()
    
    if result1:
        print(f"clinical_ops_poll_watermark.last_created_at: {result1[1]}")
    else:
        print("clinical_ops_poll_watermark.last_created_at: Not found")
    
    # Check integration_poll_watermark
    result2 = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'integration_poll_watermark' 
        AND column_name = 'last_created_at'
    """)).fetchone()
    
    if result2:
        print(f"integration_poll_watermark.last_created_at: {result2[1]}")
    else:
        print("integration_poll_watermark.last_created_at: Not found")
    
    # Check send_serviceops.created_at
    result3 = db.execute(text("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
        AND table_name = 'send_serviceops' 
        AND column_name = 'created_at'
    """)).fetchone()
    
    if result3:
        print(f"send_serviceops.created_at: {result3[1]}")
    else:
        print("send_serviceops.created_at: Not found")
        
finally:
    db.close()

