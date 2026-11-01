"""
数据库持久化模块
解决重启后数据丢失问题
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
import hashlib
import json

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

try:
    import sqlite3
    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False

from .models import Ledger, LedgerRecord, ChargeDetails, DocumentInfo, TransactionParty, FinancialAttributes


class DatabaseManager:
    """数据库管理器 - 持久化账本和处理历史"""

    def __init__(self, db_type: str = "sqlite", db_config: Optional[Dict] = None):
        """
        初始化数据库连接

        Args:
            db_type: 数据库类型 ("sqlite" 或 "postgres")
            db_config: 数据库配置
                对于 sqlite: {"database": "billing.db"}
                对于 postgres: {"host": "localhost", "database": "billing", "user": "...", "password": "..."}
        """
        self.db_type = db_type
        self.db_config = db_config or {}
        self.conn = None
        self._connect()
        self._init_tables()

    def _connect(self):
        """建立数据库连接"""
        if self.db_type == "sqlite":
            if not SQLITE_AVAILABLE:
                raise ImportError("sqlite3 not available")
            db_path = self.db_config.get("database", "billing.db")
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        elif self.db_type == "postgres":
            if not POSTGRES_AVAILABLE:
                raise ImportError("psycopg2 not installed. Run: pip install psycopg2-binary")
            self.conn = psycopg2.connect(**self.db_config)
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

    def _init_tables(self):
        """初始化数据库表"""
        cursor = self.conn.cursor()

        if self.db_type == "sqlite":
            # SQLite 表结构
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS ledger_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT UNIQUE NOT NULL,
                    document_number TEXT,
                    bill_of_lading TEXT,
                    charge_name TEXT NOT NULL,
                    standardized_name TEXT,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    payment_method TEXT,
                    posting_type TEXT,
                    accounting_entity TEXT NOT NULL,
                    record_data TEXT,  -- JSON 格式的完整记录
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS processing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    operation TEXT NOT NULL,
                    record_id TEXT,
                    model_suggestion TEXT,
                    model_confidence TEXT,
                    model_reasoning TEXT,
                    program_validation TEXT,
                    final_decision TEXT,
                    decision_data TEXT,  -- JSON 格式
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (record_id) REFERENCES ledger_records(record_id)
                );

                CREATE TABLE IF NOT EXISTS document_processing (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_hash TEXT UNIQUE NOT NULL,
                    file_name TEXT,
                    processing_status TEXT,
                    results TEXT,  -- JSON 格式
                    processed_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_document_number ON ledger_records(document_number);
                CREATE INDEX IF NOT EXISTS idx_bill_of_lading ON ledger_records(bill_of_lading);
                CREATE INDEX IF NOT EXISTS idx_record_id ON ledger_records(record_id);
            """)

        self.conn.commit()

    def save_ledger_record(self, record: LedgerRecord) -> bool:
        """
        保存或更新账本记录

        Args:
            record: 账本记录对象

        Returns:
            是否成功
        """
        cursor = self.conn.cursor()

        record_data = json.dumps(record.model_dump(), default=str, ensure_ascii=False)

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT OR REPLACE INTO ledger_records
                (record_id, document_number, bill_of_lading, charge_name, standardized_name,
                 amount, currency, payment_method, posting_type, accounting_entity, record_data, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                record.record_id,
                record.document_info.document_number,
                record.document_info.bill_of_lading,
                record.charge_details.original_name,
                record.charge_details.standardized_name,
                float(record.charge_details.amount),
                record.charge_details.currency,
                record.charge_details.payment_method,
                record.financial_attributes.posting_type,
                record.financial_attributes.accounting_entity,
                record_data
            ))

        self.conn.commit()
        return True

    def load_ledger(self, accounting_entity: str) -> Ledger:
        """
        从数据库加载账本

        Args:
            accounting_entity: 记账主体

        Returns:
            账本对象
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT record_data FROM ledger_records
            WHERE accounting_entity = ?
            ORDER BY created_at DESC
        """, (accounting_entity,))

        records = []
        for row in cursor.fetchall():
            record_dict = json.loads(row[0] if self.db_type == "sqlite" else row['record_data'])
            record = LedgerRecord(**record_dict)
            records.append(record)

        return Ledger(accounting_entity=accounting_entity, records=records)

    def save_processing_history(
        self,
        session_id: str,
        operation: str,
        record_id: Optional[str],
        model_suggestion: str,
        model_confidence: str,
        model_reasoning: str,
        program_validation: str,
        final_decision: str,
        decision_data: Dict
    ) -> bool:
        """保存处理历史"""
        cursor = self.conn.cursor()

        decision_json = json.dumps(decision_data, default=str, ensure_ascii=False)

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT INTO processing_history
                (session_id, operation, record_id, model_suggestion, model_confidence,
                 model_reasoning, program_validation, final_decision, decision_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, operation, record_id, model_suggestion, model_confidence,
                model_reasoning, program_validation, final_decision, decision_json
            ))

        self.conn.commit()
        return True

    def check_document_processed(self, file_content: bytes) -> Optional[Dict]:
        """
        检查文档是否已处理过

        Args:
            file_content: 文件内容（字节）

        Returns:
            如果已处理，返回处理结果；否则返回 None
        """
        # 计算文件哈希
        file_hash = hashlib.sha256(file_content).hexdigest()

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT results, processed_at FROM document_processing
            WHERE document_hash = ?
        """, (file_hash,))

        row = cursor.fetchone()
        if row:
            return {
                'results': json.loads(row[0] if self.db_type == "sqlite" else row['results']),
                'processed_at': row[1] if self.db_type == "sqlite" else row['processed_at']
            }

        return None

    def save_document_processing(
        self,
        file_content: bytes,
        file_name: str,
        status: str,
        results: Dict
    ) -> bool:
        """保存文档处理记录"""
        file_hash = hashlib.sha256(file_content).hexdigest()

        cursor = self.conn.cursor()

        results_json = json.dumps(results, default=str, ensure_ascii=False)

        if self.db_type == "sqlite":
            cursor.execute("""
                INSERT OR REPLACE INTO document_processing
                (document_hash, file_name, processing_status, results)
                VALUES (?, ?, ?, ?)
            """, (file_hash, file_name, status, results_json))

        self.conn.commit()
        return True

    def query_records_by_document(self, document_number: str) -> List[LedgerRecord]:
        """根据单据号查询记录"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT record_data FROM ledger_records
            WHERE document_number = ?
        """, (document_number,))

        records = []
        for row in cursor.fetchall():
            record_dict = json.loads(row[0] if self.db_type == "sqlite" else row['record_data'])
            records.append(LedgerRecord(**record_dict))

        return records

    def query_records_by_bl(self, bill_of_lading: str) -> List[LedgerRecord]:
        """根据提单号查询记录"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT record_data FROM ledger_records
            WHERE bill_of_lading = ?
        """, (bill_of_lading,))

        records = []
        for row in cursor.fetchall():
            record_dict = json.loads(row[0] if self.db_type == "sqlite" else row['record_data'])
            records.append(LedgerRecord(**record_dict))

        return records

    def get_processing_statistics(self, accounting_entity: str) -> Dict:
        """获取处理统计"""
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT document_number) as unique_documents,
                COUNT(DISTINCT bill_of_lading) as unique_bls
            FROM ledger_records
            WHERE accounting_entity = ?
        """, (accounting_entity,))

        row = cursor.fetchone()

        return {
            'total_records': row[0] if self.db_type == "sqlite" else row['total_records'],
            'unique_documents': row[1] if self.db_type == "sqlite" else row['unique_documents'],
            'unique_bls': row[2] if self.db_type == "sqlite" else row['unique_bls']
        }

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
