"""
Check packet SVC-2026-8333019 and create outbox record if missing
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.db import get_db
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.packet_validation_db import PacketValidationDB
from app.models.send_clinicalops_db import SendClinicalOpsDB
from app.models.document_db import PacketDocumentDB
from app.services.clinical_ops_outbox_service import ClinicalOpsOutboxService

db = next(get_db())

# Find packet
packet = db.query(PacketDB).filter(PacketDB.external_id == 'SVC-2026-8333019').first()
if not packet:
    print("❌ Packet not found")
    sys.exit(1)

print(f"✓ Found packet: {packet.external_id}")
print(f"  Status: {packet.detailed_status}")
print(f"  Validation Status: {packet.validation_status}")
print(f"  Decision Tracking ID: {packet.decision_tracking_id}")

# Check decision
decision = db.query(PacketDecisionDB).filter(
    PacketDecisionDB.packet_id == packet.packet_id,
    PacketDecisionDB.is_active == True
).first()

if decision:
    print(f"  Decision: operational={decision.operational_decision}, clinical={decision.clinical_decision}")
else:
    print("  ❌ No active decision found")

# Check validations
validations = db.query(PacketValidationDB).filter(
    PacketValidationDB.packet_id == packet.packet_id,
    PacketValidationDB.is_active == True
).all()

print(f"  Active Validations: {len(validations)}")
for v in validations:
    print(f"    - {v.validation_type}: is_passed={v.is_passed}, validated_by={v.validated_by}")

# Check outbox
outbox = db.query(SendClinicalOpsDB).filter(
    SendClinicalOpsDB.decision_tracking_id == str(packet.decision_tracking_id),
    SendClinicalOpsDB.is_deleted == False
).first()

if outbox:
    print(f"  ✓ Outbox record exists: message_id={outbox.message_id}")
    print(f"    Message type: {outbox.payload.get('message_type')}")
else:
    print("  ❌ No outbox record found - creating one...")
    
    # Get document
    document = db.query(PacketDocumentDB).filter(
        PacketDocumentDB.packet_id == packet.packet_id
    ).first()
    
    if document:
        try:
            outbox_record = ClinicalOpsOutboxService.send_case_ready_for_review(
                db=db,
                packet=packet,
                packet_document=document,
                created_by='system_retry'
            )
            db.commit()
            print(f"  ✓ Outbox record created: message_id={outbox_record.message_id}")
            print(f"    Message type: {outbox_record.payload.get('message_type')}")
        except Exception as e:
            print(f"  ❌ Failed to create outbox record: {e}")
            db.rollback()
    else:
        print("  ❌ No document found")

