"""Scoped additive persistence. Legacy tables remain read-only."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid

from .models import Ledger, LedgerRecord

CONFIG_VERSION = "safe-billing-v2.2"


def normalize(value):
    return " ".join(str(value or "").strip().upper().split())


def json_text(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


class DatabaseManager:
    def __init__(self, db_type="sqlite", db_config=None):
        self.db_type = db_type
        self.db_config = db_config or {}
        self._in_transaction = False
        self._legacy = False
        if db_type == "sqlite":
            path = self.db_config.get("database", str(Path(__file__).resolve().parents[2] / "output" / "billing.db"))
            if path != ":memory:":
                target = Path(path).resolve()
                if target.drive.upper() != "D:":
                    raise ValueError("数据库文件必须位于 D 盘")
                target.parent.mkdir(parents=True, exist_ok=True)
                path = str(target)
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys=ON")
            tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self._legacy = "ledger_records" in tables
            if self._legacy and "billing_charge_lines" not in tables and path != ":memory:":
                backup_dir = Path(__file__).resolve().parents[2] / "output" / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"legacy-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.db"
                with sqlite3.connect(str(backup)) as dest:
                    self.conn.backup(dest)
        elif db_type == "mysql":
            import pymysql
            self.conn = pymysql.connect(
                host=self.db_config.get("host", "localhost"), port=int(self.db_config.get("port", 3306)),
                user=self.db_config.get("user", "root"), password=self.db_config.get("password", ""),
                database=self.db_config.get("database", "ship"), charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor, autocommit=False,
            )
            self._legacy = bool(self._execute("SHOW TABLES LIKE 'ledger_records'").fetchone())
        else:
            raise ValueError("仅支持 sqlite 和 mysql；PostgreSQL 尚未实现")
        self._init_tables()

    def _execute(self, sql, params=()):
        cursor = self.conn.cursor()
        cursor.execute(sql if self.db_type == "sqlite" else sql.replace("?", "%s"), params)
        return cursor

    def _init_tables(self):
        money = "TEXT" if self.db_type == "sqlite" else "DECIMAL(24,8)"
        text = "TEXT" if self.db_type == "sqlite" else "LONGTEXT"
        statements = [
            """CREATE TABLE IF NOT EXISTS billing_scope_locks (
                accounting_entity VARCHAR(160) PRIMARY KEY)""",
            f"""CREATE TABLE IF NOT EXISTS billing_documents (
                doc_id VARCHAR(64) PRIMARY KEY, accounting_entity VARCHAR(160) NOT NULL,
                issuer VARCHAR(160) NOT NULL, document_type VARCHAR(40) NOT NULL,
                document_number VARCHAR(160) NOT NULL, document_data {text} NOT NULL,
                UNIQUE(accounting_entity, issuer, document_type, document_number))""",
            f"""CREATE TABLE IF NOT EXISTS billing_charge_lines (
                record_id VARCHAR(64) PRIMARY KEY, doc_id VARCHAR(64),
                accounting_entity VARCHAR(160) NOT NULL, document_number VARCHAR(160),
                bill_of_lading VARCHAR(160), charge_name VARCHAR(200), currency VARCHAR(10),
                amount {money}, version INTEGER NOT NULL, record_data {text} NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS billing_identifiers (
                identifier_id VARCHAR(64) PRIMARY KEY, accounting_entity VARCHAR(160) NOT NULL,
                doc_id VARCHAR(64) NOT NULL, identifier_type VARCHAR(20) NOT NULL,
                value_raw VARCHAR(160) NOT NULL, value_norm VARCHAR(160) NOT NULL)""",
            f"""CREATE TABLE IF NOT EXISTS billing_changes (
                change_id VARCHAR(64) PRIMARY KEY, session_id VARCHAR(64) NOT NULL,
                accounting_entity VARCHAR(160) NOT NULL, record_id VARCHAR(64),
                operation VARCHAR(30) NOT NULL, decision_data {text} NOT NULL,
                processed_at VARCHAR(40) NOT NULL)""",
            f"""CREATE TABLE IF NOT EXISTS billing_sources (
                accounting_entity VARCHAR(160) NOT NULL, document_hash VARCHAR(64) NOT NULL,
                config_version VARCHAR(40) NOT NULL, file_name VARCHAR(255),
                processing_status VARCHAR(30) NOT NULL, results {text} NOT NULL,
                processed_at VARCHAR(40) NOT NULL,
                PRIMARY KEY(accounting_entity, document_hash, config_version))""",
        ]
        for statement in statements:
            self._execute(statement)
        indexes = [
            ("idx_billing_doc", "billing_charge_lines", "accounting_entity,document_number"),
            ("idx_billing_bl", "billing_charge_lines", "accounting_entity,bill_of_lading"),
            ("idx_billing_charge", "billing_charge_lines", "accounting_entity,doc_id,charge_name,currency"),
            ("idx_billing_ref", "billing_identifiers", "accounting_entity,identifier_type,value_norm"),
        ]
        for name, table, cols in indexes:
            if self.db_type == "sqlite":
                self._execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
            elif not self._execute(f"SHOW INDEX FROM {table} WHERE Key_name=?", (name,)).fetchone():
                self._execute(f"CREATE INDEX {name} ON {table} ({cols})")
        self.conn.commit()

    @contextmanager
    def transaction(self):
        if self._in_transaction:
            raise RuntimeError("Nested transaction is not supported")
        self._in_transaction = True
        try:
            if self.db_type == "sqlite":
                self.conn.execute("BEGIN IMMEDIATE")
            else:
                self.conn.begin()
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self._in_transaction = False

    def _finish_write(self):
        if not self._in_transaction:
            self.conn.commit()

    @staticmethod
    def _row_record(row, legacy=False):
        data = json.loads(row["record_data"])
        if legacy and "record_kind" not in data:
            data["record_kind"] = "legacy_summary"
        return LedgerRecord.model_validate(data)

    def _rows(self, entity, column=None, value=None):
        sql = "SELECT record_data FROM billing_charge_lines WHERE accounting_entity=?"
        params = [entity]
        if column:
            sql += f" AND {column}=?"
            params.append(normalize(value))
        records = {r.record_id: r for r in
                   (self._row_record(row) for row in self._execute(sql, tuple(params)).fetchall())}
        if self._legacy:
            sql = "SELECT record_data FROM ledger_records WHERE accounting_entity=?"
            params = [entity]
            if column:
                # Legacy raw identifiers are not rewritten; normalize only this read-only compatibility path.
                sql += f" AND UPPER(TRIM({column}))=?"
                params.append(normalize(value))
            for row in self._execute(sql, tuple(params)).fetchall():
                r = self._row_record(row, True)
                records.setdefault(r.record_id, r)
        return list(records.values())

    def load_ledger(self, accounting_entity):
        records = self._rows(accounting_entity)
        return Ledger(ledger_id=str(uuid.uuid5(uuid.NAMESPACE_URL, accounting_entity)),
                      accounting_entity=accounting_entity,
                      version=sum(r.version for r in records) + 1, records=records)

    def get_record(self, record_id, accounting_entity, for_update=False):
        if for_update and not self._in_transaction:
            raise ValueError("锁定读取必须位于提交事务内")
        lock = " FOR UPDATE" if for_update and self.db_type == "mysql" else ""
        row = self._execute("SELECT record_data FROM billing_charge_lines WHERE accounting_entity=? AND record_id=?" + lock,
                            (accounting_entity, record_id)).fetchone()
        if row:
            return self._row_record(row)
        if self._legacy:
            row = self._execute("SELECT record_data FROM ledger_records WHERE accounting_entity=? AND record_id=?" + lock,
                                (accounting_entity, record_id)).fetchone()
            if row:
                return self._row_record(row, True)
        return None

    def query_records_by_document(self, document_number, accounting_entity=None):
        if not accounting_entity:
            raise ValueError("查询必须指定记账主体")
        return self._rows(accounting_entity, "document_number", document_number)

    def query_records_by_bl(self, bill_of_lading, accounting_entity=None):
        if not accounting_entity:
            raise ValueError("查询必须指定记账主体")
        return self._rows(accounting_entity, "bill_of_lading", bill_of_lading)

    def query_records_by_identifier(self, kind, value, accounting_entity):
        rows = self._execute("""SELECT c.record_data FROM billing_charge_lines c
            JOIN billing_identifiers i ON i.doc_id=c.doc_id AND i.accounting_entity=c.accounting_entity
            WHERE i.accounting_entity=? AND i.identifier_type=? AND i.value_norm=?""",
                             (accounting_entity, kind, normalize(value))).fetchall()
        return list({r.record_id: r for r in (self._row_record(row) for row in rows)}.values())

    def _ensure_document(self, record):
        doc = record.document_info
        entity = record.financial_attributes.accounting_entity
        key = [entity, normalize(record.transaction_party.issuer),
               normalize(doc.document_type), normalize(doc.document_number)]
        # Structured encoding preserves component boundaries and the exact bookkeeping scope.
        identity = json_text(["document", *key]) if all(key) else json_text(["reviewed", entity, record.record_id])
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        if not self._execute("SELECT doc_id FROM billing_documents WHERE doc_id=?", (doc_id,)).fetchone():
            self._execute("INSERT INTO billing_documents VALUES (?,?,?,?,?,?)",
                          (doc_id, entity, key[1] or doc_id, key[2], key[3] or doc_id, json_text(doc)))
        refs = [("MBL", getattr(doc, "master_bill_of_lading", None)),
                ("HBL", getattr(doc, "house_bill_of_lading", None)),
                ("BL", doc.bill_of_lading), ("BOOKING", doc.booking_number)]
        refs += [("CONTAINER", v) for v in getattr(doc, "container_numbers", [])]
        if doc.container_number:
            refs.append(("CONTAINER", doc.container_number))
        for kind, value in dict.fromkeys((k, v) for k, v in refs if v):
            ref_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json_text([entity, doc_id, kind, normalize(value)])))
            if not self._execute("SELECT identifier_id FROM billing_identifiers WHERE identifier_id=?", (ref_id,)).fetchone():
                self._execute("INSERT INTO billing_identifiers VALUES (?,?,?,?,?,?)",
                              (ref_id, entity, doc_id, kind, value, normalize(value)))
        record.doc_id = doc_id
        return doc_id

    def save_ledger_record(self, record, expected_version=None):
        entity = record.financial_attributes.accounting_entity
        existing = self._execute("SELECT accounting_entity,version FROM billing_charge_lines WHERE record_id=?",
                                 (record.record_id,)).fetchone()
        if existing and existing["accounting_entity"] != entity:
            raise ValueError("禁止跨记账主体覆盖记录")
        if not record.charge_details.amount.is_finite():
            raise ValueError("金额必须是有限十进制数")
        amount = record.charge_details.amount
        if amount.adjusted() >= 16 or amount.normalize().as_tuple().exponent < -8:
            raise ValueError("金额超出数据库精度，禁止静默舍入")
        if expected_version is not None:
            if record.version != expected_version + 1:
                raise ValueError("更新后的记录版本必须递增一次")
            if not existing:
                # An explicitly reviewed legacy summary is copied into the new tables;
                # its original table is never overwritten or split automatically.
                legacy = self.get_record(record.record_id, entity, for_update=self._in_transaction)
                if not legacy or legacy.version != expected_version:
                    raise ValueError("记录版本已变化，请重新预览")
        doc_id = self._ensure_document(record)
        values = (doc_id, entity, normalize(record.document_info.document_number),
                  normalize(record.document_info.bill_of_lading), normalize(record.charge_details.original_name),
                  record.charge_details.currency, str(record.charge_details.amount), record.version, json_text(record))
        if existing:
            predicate = " WHERE record_id=? AND accounting_entity=?"
            params = values + (record.record_id, entity)
            if expected_version is not None:
                predicate += " AND version=?"
                params += (expected_version,)
            cursor = self._execute("""UPDATE billing_charge_lines SET doc_id=?,accounting_entity=?,document_number=?,
                bill_of_lading=?,charge_name=?,currency=?,amount=?,version=?,record_data=?""" + predicate, params)
            if expected_version is not None and cursor.rowcount != 1:
                raise ValueError("记录版本已变化，请重新预览")
        else:
            self._execute("INSERT INTO billing_charge_lines VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (record.record_id,) + values)
        self._finish_write()
        return True

    def _write_change(self, session_id, entity, plan):
        data = {"old_values": plan.get("before"), "new_values": plan.get("after"),
                "patch": plan.get("patch", {}), "evidence": plan.get("evidence", []),
                "revision_evidence": plan.get("revision_evidence", []), "reason": plan.get("reason"),
                "review": plan.get("review")}
        self._execute("INSERT INTO billing_changes VALUES (?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), session_id, entity, plan.get("record_id"), plan["operation"],
                       json_text(data), datetime.now().isoformat()))

    def _claim_sources(self, source_events, accounting_entity, has_creates):
        """Acquire a unique source row before writes, including for new MySQL sources."""
        for event in {event["document_hash"]: event for event in source_events}.values():
            key = (accounting_entity, event["document_hash"], CONFIG_VERSION)
            values = key + (event.get("file_name", ""), "processing", "{}", datetime.now().isoformat())
            if self.db_type == "sqlite":
                self._execute("INSERT OR IGNORE INTO billing_sources VALUES (?,?,?,?,?,?,?)", values)
            else:
                # A no-op duplicate update acquires the existing row lock without erasing
                # the completed status which the next current read must inspect.
                self._execute("""INSERT INTO billing_sources VALUES (?,?,?,?,?,?,?)
                    ON DUPLICATE KEY UPDATE document_hash=VALUES(document_hash)""", values)
            lock = " FOR UPDATE" if self.db_type == "mysql" else ""
            row = self._execute("""SELECT processing_status FROM billing_sources WHERE accounting_entity=?
                AND document_hash=? AND config_version=?""" + lock, key).fetchone()
            if row["processing_status"] in {"committed", "no_change"} and has_creates:
                raise ValueError("来源已提交，重复新增已阻止，请重新预览")

    def _lock_scope(self, accounting_entity):
        """Serialize billing commits for one bookkeeping scope across connections."""
        if not self._in_transaction:
            raise ValueError("账套锁必须位于提交事务内")
        insert = "INSERT OR IGNORE" if self.db_type == "sqlite" else "INSERT IGNORE"
        self._execute(f"{insert} INTO billing_scope_locks (accounting_entity) VALUES (?)", (accounting_entity,))
        lock = " FOR UPDATE" if self.db_type == "mysql" else ""
        self._execute("SELECT accounting_entity FROM billing_scope_locks WHERE accounting_entity=?" + lock,
                      (accounting_entity,)).fetchone()

    def _check_create_candidates(self, plans, accounting_entity, baseline_records):
        """Detect new business candidates before applying any plans in this batch."""
        baselines = [raw if isinstance(raw, LedgerRecord) else LedgerRecord.model_validate(raw)
                     for raw in baseline_records or []]
        for plan in plans:
            if plan["operation"] != "CREATE":
                continue
            after = LedgerRecord.model_validate(plan["after"])
            number = after.document_info.document_number
            if not number:
                # Explicit manual creations with incomplete identifiers cannot be
                # assigned an invented document identity or uniqueness guarantee.
                continue
            rows = self.query_records_by_document(number, accounting_entity)
            rows += [r for r in baselines if r.financial_attributes.accounting_entity == accounting_entity
                     and normalize(r.document_info.document_number) == normalize(number)]
            candidates = {r["record_id"]: r for r in plan.get("candidates", [])}
            for current in {r.record_id: r for r in rows}.values():
                if normalize(current.transaction_party.issuer) != normalize(after.transaction_party.issuer):
                    continue
                if normalize(current.document_info.document_type) != normalize(after.document_info.document_type):
                    continue
                same_name = normalize(current.charge_details.original_name) == normalize(after.charge_details.original_name)
                same_code = bool(after.charge_details.standardized_name and current.charge_details.standardized_name
                                 and normalize(after.charge_details.standardized_name)
                                 == normalize(current.charge_details.standardized_name))
                if same_name or same_code:
                    preview = candidates.get(current.record_id)
                    if not preview or preview.get("version") != current.version:
                        raise ValueError("业务候选已变化，请重新预览")

    def _import_baseline(self, baseline_records, accounting_entity):
        for raw in baseline_records or []:
            if isinstance(raw, LedgerRecord):
                record = raw.model_copy(deep=True)
            else:
                data = dict(raw)
                if "record_kind" not in data:
                    data["record_kind"] = "legacy_summary"
                record = LedgerRecord.model_validate(data)
            if record.financial_attributes.accounting_entity != accounting_entity:
                raise ValueError("上传旧账记账主体不一致")
            current = self.get_record(record.record_id, accounting_entity, for_update=True)
            if current:
                # doc_id is generated persistence metadata; an omitted id in an
                # otherwise identical uploaded record is not a business conflict.
                same = record.model_dump(exclude={"doc_id"}) == current.model_dump(exclude={"doc_id"})
                if not same or (record.doc_id and record.doc_id != current.doc_id):
                    raise ValueError("上传旧账与当前账本存在冲突，请重新导出核对")
            else:
                self.save_ledger_record(record)

    def commit_plans(self, plans, source_events, session_id, accounting_entity, baseline_records=None):
        with self.transaction():
            self._lock_scope(accounting_entity)
            self._check_create_candidates(plans, accounting_entity, baseline_records)
            self._claim_sources(source_events, accounting_entity,
                                any(plan["operation"] == "CREATE" for plan in plans))
            self._import_baseline(baseline_records, accounting_entity)
            touched = set()
            for plan in plans:
                if plan["operation"] == "PENDING_REVIEW":
                    continue
                record_id = plan.get("record_id")
                if record_id in touched:
                    raise ValueError("同一批次不能多次修改同一费用")
                touched.add(record_id)
                if plan["operation"] not in {"CREATE", "UPDATE", "NO_CHANGE"}:
                    raise ValueError("不支持的提交操作")
                current = self.get_record(record_id, accounting_entity, for_update=True) if record_id else None
                if plan["operation"] in ("UPDATE", "NO_CHANGE"):
                    if not current or current.version != plan["expected_version"]:
                        raise ValueError("记录版本已变化，请重新预览")
                elif current:
                    raise ValueError("新增记录已存在，请重新预览")
                if plan["operation"] in ("CREATE", "UPDATE"):
                    after = LedgerRecord.model_validate(plan["after"])
                    if after.record_id != record_id:
                        raise ValueError("提交记录ID与预览身份不一致")
                    if after.financial_attributes.accounting_entity != accounting_entity:
                        raise ValueError("记账主体不一致")
                    self.save_ledger_record(after, expected_version=plan["expected_version"]
                                            if plan["operation"] == "UPDATE" else None)
                self._write_change(session_id, accounting_entity, plan)
            for event in source_events:
                self._save_source(event["document_hash"], event.get("file_name", ""), event["status"],
                                  event.get("results", {}), accounting_entity)
        return self.load_ledger(accounting_entity)

    def _save_source(self, file_hash, file_name, status, results, accounting_entity):
        key = (accounting_entity, file_hash, CONFIG_VERSION)
        exists = self._execute("SELECT document_hash FROM billing_sources WHERE accounting_entity=? AND document_hash=? AND config_version=?", key).fetchone()
        values = (file_name, status, json_text(results), datetime.now().isoformat())
        if exists:
            self._execute("UPDATE billing_sources SET file_name=?,processing_status=?,results=?,processed_at=? WHERE accounting_entity=? AND document_hash=? AND config_version=?", values + key)
        else:
            self._execute("INSERT INTO billing_sources VALUES (?,?,?,?,?,?,?)", key + values)

    def save_document_processing(self, file_content, file_name, status, results, accounting_entity=None):
        if not accounting_entity:
            raise ValueError("文件状态必须指定记账主体")
        self._save_source(hashlib.sha256(file_content).hexdigest(), file_name, status, results, accounting_entity)
        self._finish_write()
        return True

    def check_document_processed(self, file_content, accounting_entity=None, processing_signature=None):
        if not accounting_entity:
            raise ValueError("文件查重必须指定记账主体")
        row = self._execute("""SELECT * FROM billing_sources WHERE accounting_entity=? AND document_hash=?
            AND config_version=? AND processing_status IN ('committed','no_change')""",
                            (accounting_entity, hashlib.sha256(file_content).hexdigest(), CONFIG_VERSION)).fetchone()
        if row:
            results = json.loads(row["results"])
            if processing_signature is not None and results.get("processing_signature") != processing_signature:
                return None
            versions = results.get("record_versions", {})
            if not isinstance(versions, dict):
                return None
            for record_id, version in versions.items():
                current = self.get_record(record_id, accounting_entity)
                if current is None or current.version != version:
                    return None
            return {"results": results, "processed_at": row["processed_at"]}
        return None

    def save_processing_history(self, session_id, operation, record_id=None, decision_data=None,
                                accounting_entity=None, **kwargs):
        if not accounting_entity:
            raise ValueError("审计必须指定记账主体")
        self._write_change(session_id, accounting_entity,
                           {"operation": operation, "record_id": record_id, "after": decision_data or {}})
        self._finish_write()
        return True

    def get_processing_statistics(self, accounting_entity):
        records = self.load_ledger(accounting_entity).records
        return {"total_records": len(records),
                "unique_documents": len({r.document_info.document_number for r in records if r.document_info.document_number}),
                "unique_bls": len({r.document_info.bill_of_lading for r in records if r.document_info.bill_of_lading}),
                "legacy_summaries": sum(getattr(r, "record_kind", "") == "legacy_summary" for r in records)}

    def close(self):
        if getattr(self, "conn", None):
            self.conn.close()
            self.conn = None
