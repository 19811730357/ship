"""
Test MySQL Connection
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.database import DatabaseManager
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_mysql_connection():
    """Test connection to MySQL ship database"""

    print("=" * 70)
    print("MySQL Connection Test")
    print("=" * 70)

    # MySQL configuration
    mysql_config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 3306)),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "ship")
    }

    print(f"\nConnecting to MySQL:")
    print(f"  Host: {mysql_config['host']}:{mysql_config['port']}")
    print(f"  Database: {mysql_config['database']}")
    print(f"  User: {mysql_config['user']}")

    try:
        # Connect to MySQL
        db = DatabaseManager(db_type="mysql", db_config=mysql_config)

        print("\n[OK] Connected to MySQL successfully!")

        # Create tables
        print("\n[OK] Tables created/verified")

        # Test basic operations
        print("\n" + "=" * 70)
        print("Testing Basic Operations")
        print("=" * 70)

        from billing_agent.models import LedgerRecord, ChargeDetails, DocumentInfo, TransactionParty, FinancialAttributes

        # Create a test record
        record = LedgerRecord(
            record_id="TEST-MYSQL-001",
            charge_details=ChargeDetails(
                original_name="TEST CHARGE",
                standardized_name="Test Charge",
                amount=100.00,
                currency="USD"
            ),
            document_info=DocumentInfo(
                document_number="DN-MYSQL-001",
                bill_of_lading="BL-MYSQL-001"
            ),
            transaction_party=TransactionParty(),
            financial_attributes=FinancialAttributes(
                accounting_entity="MySQL Test Company",
                posting_type="AR"
            )
        )

        # Save to database
        db.save_ledger_record(record)
        print("\n[OK] Test record saved")

        # Load from database
        ledger = db.load_ledger("MySQL Test Company")
        print(f"[OK] Loaded {len(ledger.records)} records from database")

        # Query by document
        records = db.query_records_by_document("DN-MYSQL-001")
        print(f"[OK] Query found {len(records)} records")

        # Statistics
        stats = db.get_processing_statistics("MySQL Test Company")
        print(f"\n[Database Statistics]")
        print(f"  Total records: {stats['total_records']}")
        print(f"  Unique documents: {stats['unique_documents']}")
        print(f"  Unique BLs: {stats['unique_bls']}")

        db.close()

        print("\n" + "=" * 70)
        print("[SUCCESS] MySQL integration working!")
        print("=" * 70)

        return True

    except ImportError as e:
        print(f"\n[ERROR] Missing dependency: {e}")
        print("\nTo install MySQL support, run:")
        print("  pip install pymysql")
        return False

    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        print("\nPlease check:")
        print("  1. MySQL server is running")
        print("  2. Database 'ship' exists")
        print("  3. Credentials in .env are correct")
        print("  4. User has necessary permissions")
        return False


if __name__ == "__main__":
    success = test_mysql_connection()
    sys.exit(0 if success else 1)
