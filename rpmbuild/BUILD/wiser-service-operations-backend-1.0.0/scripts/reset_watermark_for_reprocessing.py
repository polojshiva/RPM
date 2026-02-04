"""
Script to reset watermark for reprocessing failed messages

This script resets the integration_poll_watermark to a date before the failed messages,
allowing them to be picked up and reprocessed by the poller.

Usage:
    python scripts/reset_watermark_for_reprocessing.py --before-date "2026-01-10 00:00:00"
    python scripts/reset_watermark_for_reprocessing.py --message-ids 594,593,592,591,601,598,597,121,120,119,361,306,602
    python scripts/reset_watermark_for_reprocessing.py --reset-to-beginning  # Reset to 1970-01-01
"""
import sys
import argparse
from datetime import datetime, timezone
from sqlalchemy import text

# Add parent directory to path
sys.path.insert(0, '.')

from app.services.db import SessionLocal


def reset_watermark_before_date(before_date: datetime):
    """Reset watermark to before a specific date"""
    db = SessionLocal()
    try:
        db.execute(
            text("""
                UPDATE service_ops.integration_poll_watermark
                SET last_created_at = :before_date,
                    last_message_id = 0
                WHERE id = 1
            """),
            {'before_date': before_date}
        )
        db.commit()
        print(f"✅ Watermark reset to: {before_date}")
        print(f"   All messages created after this date will be reprocessed")
    except Exception as e:
        db.rollback()
        print(f"❌ Error resetting watermark: {e}")
        raise
    finally:
        db.close()


def reset_watermark_for_message_ids(message_ids: list):
    """Reset watermark to before the earliest message_id"""
    db = SessionLocal()
    try:
        # Find the earliest created_at for these message_ids
        result = db.execute(
            text("""
                SELECT MIN(created_at) as min_created_at, MIN(message_id) as min_message_id
                FROM integration.send_serviceops
                WHERE message_id = ANY(:message_ids)
            """),
            {'message_ids': message_ids}
        ).fetchone()
        
        if not result or not result[0]:
            print(f"❌ No messages found with those IDs")
            return
        
        min_created_at = result[0]
        min_message_id = result[1] or 0
        
        # Reset watermark to just before the earliest message
        # Subtract 1 second to ensure it's picked up
        before_date = min_created_at.replace(second=min_created_at.second - 1) if min_created_at.second > 0 else min_created_at
        
        db.execute(
            text("""
                UPDATE service_ops.integration_poll_watermark
                SET last_created_at = :before_date,
                    last_message_id = :min_message_id - 1
                WHERE id = 1
            """),
            {
                'before_date': before_date,
                'min_message_id': min_message_id
            }
        )
        db.commit()
        print(f"✅ Watermark reset to: {before_date}, message_id={min_message_id - 1}")
        print(f"   Messages {message_ids} will be reprocessed")
    except Exception as e:
        db.rollback()
        print(f"❌ Error resetting watermark: {e}")
        raise
    finally:
        db.close()


def reset_watermark_to_beginning():
    """Reset watermark to beginning (1970-01-01) - reprocesses ALL messages"""
    db = SessionLocal()
    try:
        db.execute(
            text("""
                UPDATE service_ops.integration_poll_watermark
                SET last_created_at = '1970-01-01 00:00:00+00'::timestamptz,
                    last_message_id = 0
                WHERE id = 1
            """)
        )
        db.commit()
        print(f"✅ Watermark reset to beginning (1970-01-01)")
        print(f"   ⚠️  WARNING: This will reprocess ALL messages in integration.send_serviceops")
        print(f"   Make sure you want to do this!")
    except Exception as e:
        db.rollback()
        print(f"❌ Error resetting watermark: {e}")
        raise
    finally:
        db.close()


def show_current_watermark():
    """Show current watermark position"""
    db = SessionLocal()
    try:
        result = db.execute(
            text("""
                SELECT last_created_at, last_message_id
                FROM service_ops.integration_poll_watermark
                WHERE id = 1
            """)
        ).fetchone()
        
        if result:
            print(f"Current watermark:")
            print(f"  last_created_at: {result[0]}")
            print(f"  last_message_id: {result[1]}")
        else:
            print("No watermark found (will default to 1970-01-01)")
    except Exception as e:
        print(f"❌ Error reading watermark: {e}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='Reset watermark for reprocessing failed messages')
    parser.add_argument('--before-date', type=str, help='Reset watermark to before this date (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--message-ids', type=str, help='Comma-separated list of message_ids to reprocess')
    parser.add_argument('--reset-to-beginning', action='store_true', help='Reset watermark to beginning (reprocesses ALL messages)')
    parser.add_argument('--show', action='store_true', help='Show current watermark position')
    
    args = parser.parse_args()
    
    if args.show:
        show_current_watermark()
        return
    
    if args.reset_to_beginning:
        confirm = input("⚠️  Are you sure you want to reset watermark to beginning? This will reprocess ALL messages. (yes/no): ")
        if confirm.lower() == 'yes':
            reset_watermark_to_beginning()
        else:
            print("Cancelled")
        return
    
    if args.before_date:
        try:
            before_date = datetime.strptime(args.before_date, '%Y-%m-%d %H:%M:%S')
            before_date = before_date.replace(tzinfo=timezone.utc)
            reset_watermark_before_date(before_date)
        except ValueError as e:
            print(f"❌ Invalid date format. Use: YYYY-MM-DD HH:MM:SS")
            print(f"   Error: {e}")
        return
    
    if args.message_ids:
        try:
            message_ids = [int(x.strip()) for x in args.message_ids.split(',')]
            reset_watermark_for_message_ids(message_ids)
        except ValueError as e:
            print(f"❌ Invalid message_ids format. Use comma-separated integers")
            print(f"   Error: {e}")
        return
    
    # Default: show current watermark
    show_current_watermark()
    print("\nUsage examples:")
    print("  python scripts/reset_watermark_for_reprocessing.py --before-date '2026-01-10 00:00:00'")
    print("  python scripts/reset_watermark_for_reprocessing.py --message-ids 594,593,592,591")
    print("  python scripts/reset_watermark_for_reprocessing.py --reset-to-beginning")


if __name__ == '__main__':
    main()

