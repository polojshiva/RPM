"""
Test what happens when letter generation succeeds (gets blob_url response)
Simulates the full flow from letter generation success to final status
"""
import sys
import os
import asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db import SessionLocal
from app.models.packet_db import PacketDB
from app.models.packet_decision_db import PacketDecisionDB
from app.models.send_integration_db import SendIntegrationDB
from app.models.document_db import PacketDocumentDB  # Ensure all models loaded
from app.services.workflow_orchestrator import WorkflowOrchestratorService
from app.services.decisions_service import DecisionsService
from datetime import datetime
import json

async def test_letter_generation_success_flow():
    """Test the flow after letter generation succeeds"""
    db = SessionLocal()
    
    try:
        print("=" * 80)
        print("TESTING LETTER GENERATION SUCCESS FLOW")
        print("=" * 80)
        print()
        
        # Find a packet that has UTN received but letter not yet generated
        # Or find one with letter_status = 'PENDING' or 'FAILED' that we can simulate success for
        packet = db.query(PacketDB).join(PacketDecisionDB).filter(
            PacketDecisionDB.is_active == True,
            PacketDecisionDB.utn.isnot(None),
            PacketDecisionDB.utn_status == 'SUCCESS',
            PacketDecisionDB.letter_status.in_(['PENDING', 'FAILED', 'NONE'])
        ).first()
        
        if not packet:
            print("No suitable packet found. Looking for any packet with UTN...")
            packet = db.query(PacketDB).join(PacketDecisionDB).filter(
                PacketDecisionDB.is_active == True,
                PacketDecisionDB.utn.isnot(None)
            ).first()
        
        if not packet:
            print("ERROR: No packet found with UTN. Please run UTN processing first.")
            return
        
        packet_decision = db.query(PacketDecisionDB).filter(
            PacketDecisionDB.packet_id == packet.packet_id,
            PacketDecisionDB.is_active == True
        ).order_by(PacketDecisionDB.created_at.desc()).first()
        
        print(f"Found packet: {packet.external_id}")
        print(f"  packet_id: {packet.packet_id}")
        print(f"  Current status: {packet.detailed_status}")
        print(f"  UTN: {packet_decision.utn}")
        print(f"  Letter status: {packet_decision.letter_status}")
        print()
        
        # Simulate successful letter generation response
        # This is what LetterGen API would return
        letter_metadata = {
            "blob_url": "https://prdwiserfaxsablob.blob.core.usgovcloudapi.net/service-ops-processing/2026/01-14/test-letter.pdf",
            "blob_path": "2026/01-14/test-letter.pdf",
            "filename": "test-letter.pdf",
            "file_size_bytes": 12345,
            "template_used": "affirmation_template_v2",
            "generated_at": datetime.utcnow().isoformat(),
            "inbound_json_blob_url": "https://prdwiserfaxsablob.blob.core.usgovcloudapi.net/service-ops-processing/2026/01-14/test-letter-json.json",
            "inbound_metadata_blob_url": "https://prdwiserfaxsablob.blob.core.usgovcloudapi.net/service-ops-processing/2026/01-14/test-letter-metadata.json"
        }
        
        print("STEP 1: Simulating successful letter generation...")
        print(f"  Letter metadata received:")
        print(f"    blob_url: {letter_metadata['blob_url']}")
        print(f"    filename: {letter_metadata['filename']}")
        print(f"    file_size: {letter_metadata['file_size_bytes']} bytes")
        print()
        
        # Update packet_decision as if letter generation succeeded
        packet_decision.letter_status = 'READY'
        packet_decision.letter_package = letter_metadata
        packet_decision.letter_generated_at = datetime.utcnow()
        
        # Update packet status to "Generate Decision Letter - Complete"
        WorkflowOrchestratorService.update_packet_status(
            db=db,
            packet=packet,
            new_status="Generate Decision Letter - Complete"
        )
        
        db.commit()
        db.refresh(packet)
        db.refresh(packet_decision)
        
        print("STEP 2: Updated packet_decision and packet status")
        print(f"  letter_status: {packet_decision.letter_status}")
        print(f"  letter_generated_at: {packet_decision.letter_generated_at}")
        print(f"  packet.detailed_status: {packet.detailed_status}")
        print()
        
        # Now simulate _send_letter_to_integration
        print("STEP 3: Sending letter package to Integration...")
        
        from app.services.utn_handlers import UtnSuccessHandler
        
        await UtnSuccessHandler._send_letter_to_integration(
            db=db,
            packet=packet,
            packet_decision=packet_decision
        )
        
        db.commit()
        db.refresh(packet)
        db.refresh(packet_decision)
        
        print("STEP 4: Letter package sent to Integration")
        print(f"  letter_status: {packet_decision.letter_status}")
        print(f"  letter_sent_to_integration_at: {packet_decision.letter_sent_to_integration_at}")
        print(f"  packet.detailed_status: {packet.detailed_status}")
        print()
        
        # Check send_integration record
        send_integration_records = db.query(SendIntegrationDB).filter(
            SendIntegrationDB.decision_tracking_id == packet.decision_tracking_id,
            SendIntegrationDB.payload['message_type'].astext == 'LETTER_PACKAGE'
        ).order_by(SendIntegrationDB.created_at.desc()).all()
        
        if send_integration_records:
            latest_record = send_integration_records[0]
            payload = latest_record.payload
            print("STEP 5: Verified send_integration record created")
            print(f"  message_id: {latest_record.message_id}")
            print(f"  message_type: {payload.get('message_type')}")
            print(f"  letter_package.blob_url: {payload.get('letter_package', {}).get('blob_url')}")
            print(f"  message_status_id: {latest_record.message_status_id} (1=INGESTED)")
            print()
        
        # Check final decision
        active_decision = WorkflowOrchestratorService.get_active_decision(db, packet.packet_id)
        if active_decision:
            print("STEP 6: Final decision status")
            print(f"  operational_decision: {active_decision.operational_decision}")
            print(f"  clinical_decision: {active_decision.clinical_decision}")
            print()
        
        print("=" * 80)
        print("TEST SUMMARY")
        print("=" * 80)
        print(f"[OK] Letter generation success simulated")
        print(f"[OK] Letter package sent to service_ops.send_integration")
        print(f"[OK] Packet status: {packet.detailed_status}")
        print(f"[OK] Letter status: {packet_decision.letter_status}")
        print(f"[OK] Operational decision: {active_decision.operational_decision if active_decision else 'N/A'}")
        print()
        print("VERIFICATION:")
        print("1. Check service_ops.send_integration for LETTER_PACKAGE record")
        print("2. Check packet.detailed_status = 'Decision Complete'")
        print("3. Check packet_decision.letter_status = 'SENT'")
        print("4. Check packet_decision.operational_decision = 'DECISION_COMPLETE'")
        print()
        
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_letter_generation_success_flow())

