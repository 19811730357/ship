"""
Quick Database Integration Test
Tests data persistence and UPDATE recognition after restart
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.database import DatabaseManager
from billing_agent.models import LedgerRecord, ChargeDetails, DocumentInfo, TransactionParty, FinancialAttributes, Evidence
import uuid


def test_simple():
    """Simple database test"""

    print("=" * 70)
    print("DATABASE INTEGRATION TEST")
    print("=" * 70)

    # Initialize database
    db = DatabaseManager(db_type="sqlite", db_config={"database": "test_billing.db"})

    print("\n[Step 1] Create first record")
    print("-" * 70)

    # Create record 1
    record1 = LedgerRecord(
        record_id="REC-001",
        charge_details=ChargeDetails(
            original_name="HANDLING CHARGE",
            standardized_name="Handling Charge",
            amount=50.00,
            currency="USD"
        ),
        document_info=DocumentInfo(
            document_number="DN-TEST-001",
            bill_of_lading="BL-TEST-001"
        ),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(
            accounting_entity="Test Company",
            posting_type="AR"
        )
    )

    db.save_ledger_record(record1)
    print("[OK] Saved record: HANDLING CHARGE - 50 USD")

    # Check database
    stats = db.get_processing_statistics("Test Company")
    print(f"\n[Database Stats]")
    print(f"  Total records: {stats['total_records']}")
    print(f"  Unique docs: {stats['unique_documents']}")
    print(f"  Unique BLs: {stats['unique_bls']}")

    # Simulate restart
    print("\n" + "=" * 70)
    print("[Step 2] Simulate restart - Close and reopen database")
    print("=" * 70)

    db.close()
    db2 = DatabaseManager(db_type="sqlite", db_config={"database": "test_billing.db"})

    # Load from database
    ledger = db2.load_ledger("Test Company")
    print(f"\n[OK] Loaded from database: {len(ledger.records)} records")

    if len(ledger.records) > 0:
        print(f"\n[Records in database]")
        for record in ledger.records:
            print(f"  - {record.charge_details.original_name}: "
                  f"{record.charge_details.amount} {record.charge_details.currency}")
            print(f"    Doc: {record.document_info.document_number}")
            print(f"    BL: {record.document_info.bill_of_lading}")

    # Update record
    print("\n" + "=" * 70)
    print("[Step 3] Update existing record")
    print("=" * 70)

    # Query by document
    records = db2.query_records_by_document("DN-TEST-001")
    print(f"\n[Query] Found {len(records)} records for DN-TEST-001")

    if records:
        # Update the first record
        old_record = records[0]
        print(f"[Before] {old_record.charge_details.original_name}: {old_record.charge_details.amount} {old_record.charge_details.currency}")

        # Create updated record
        updated_record = LedgerRecord(
            record_id=old_record.record_id,  # Same ID = UPDATE
            charge_details=ChargeDetails(
                original_name="HANDLING CHARGE",
                standardized_name="Handling Charge",
                amount=40.00,  # Changed from 50 to 40
                currency="USD"
            ),
            document_info=old_record.document_info,
            transaction_party=old_record.transaction_party,
            financial_attributes=old_record.financial_attributes
        )

        db2.save_ledger_record(updated_record)
        print(f"[After] {updated_record.charge_details.original_name}: {updated_record.charge_details.amount} {updated_record.charge_details.currency}")
        print("[OK] Record updated in database")

    # Final stats
    print("\n" + "=" * 70)
    print("[Step 4] Final verification")
    print("=" * 70)

    ledger_final = db2.load_ledger("Test Company")
    print(f"\n[Final ledger] {len(ledger_final.records)} records")

    for record in ledger_final.records:
        print(f"  - {record.charge_details.original_name}: "
              f"{record.charge_details.amount} {record.charge_details.currency}")

    stats_final = db2.get_processing_statistics("Test Company")
    print(f"\n[Final Database Stats]")
    print(f"  Total records: {stats_final['total_records']}")
    print(f"  Unique docs: {stats_final['unique_documents']}")
    print(f"  Unique BLs: {stats_final['unique_bls']}")

    db2.close()

    # Verify
    print("\n" + "=" * 70)
    print("[RESULT]")
    print("=" * 70)

    if stats_final['total_records'] == 1:
        print("[PASS] Database persistence works!")
        print("[PASS] Update operation preserved record count")
        print("[PASS] Data survived restart")
        return True
    else:
        print("[FAIL] Expected 1 record, got", stats_final['total_records'])
        return False


if __name__ == "__main__":
    try:
        success = test_simple()
        print("\n" + "=" * 70)
        if success:
            print("TEST PASSED!")
        else:
            print("TEST FAILED!")
        print("=" * 70)
        print("\nDatabase file: test_billing.db")
        print("You can inspect it with: sqlite3 test_billing.db")
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
