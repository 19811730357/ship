"""Commit boundaries protect against stale previews and duplicate submissions."""

import hashlib
from decimal import Decimal

import pytest

from src.billing_agent.database import DatabaseManager
from src.billing_agent.models import (
    ChargeDetails, DocumentInfo, FinancialAttributes, LedgerRecord, TransactionParty,
)


def record(record_id="charge-1", amount="50", entity="A", issuer="Issuer", version=1):
    return LedgerRecord(
        record_id=record_id, version=version,
        charge_details=ChargeDetails(original_name="HANDLING", amount=amount, currency="USD"),
        document_info=DocumentInfo(document_type="INVOICE", document_number="INV-1"),
        transaction_party=TransactionParty(issuer=issuer),
        financial_attributes=FinancialAttributes(accounting_entity=entity, posting_type="AP"),
    )


def plan(after, operation="CREATE", before=None):
    return {"operation": operation, "record_id": after.record_id,
            "expected_version": before.version if before else None,
            "before": before.model_dump(mode="json") if before else None,
            "after": after.model_dump(mode="json"), "patch": {}, "reason": "tested plan"}


def event(content=b"same bill", signature="model-and-policy-1"):
    return {"document_hash": hashlib.sha256(content).hexdigest(), "file_name": "bill.txt",
            "status": "committed", "results": {"processing_signature": signature}}


@pytest.fixture
def db():
    manager = DatabaseManager("sqlite", {"database": ":memory:"})
    yield manager
    manager.close()


def test_two_previews_of_same_new_source_cannot_create_twice(db):
    first, second = plan(record("first")), plan(record("second"))
    db.commit_plans([first], [event()], "session-first", "A")
    with pytest.raises(ValueError, match="重复|预览|处理|source"):
        db.commit_plans([second], [event()], "session-second", "A")
    assert [r.record_id for r in db.load_ledger("A").records] == ["first"]


def test_pending_source_is_not_a_completed_source_claim(db):
    db.save_document_processing(b"same bill", "bill.txt", "pending_review", {}, "A")
    db.commit_plans([plan(record())], [event()], "session-retry", "A")
    assert len(db.load_ledger("A").records) == 1


def test_same_source_in_different_entity_is_independent(db):
    db.commit_plans([plan(record("a", entity="A"))], [event()], "session-a", "A")
    db.commit_plans([plan(record("b", entity="B"))], [event()], "session-b", "B")
    assert len(db.load_ledger("A").records) == len(db.load_ledger("B").records) == 1


def test_explicit_uploaded_baseline_and_plans_commit_together(db):
    baseline = record("uploaded", version=7)
    after = baseline.model_copy(deep=True)
    after.version, after.charge_details.amount = 8, Decimal("40")
    db.commit_plans([plan(after, "UPDATE", baseline)], [], "session-import", "A",
                    baseline_records=[baseline])
    assert db.get_record("uploaded", "A").version == 8
    assert db.get_record("uploaded", "A").charge_details.amount == Decimal("40")


def test_conflicting_uploaded_baseline_does_not_overwrite_or_partially_import(db):
    existing = record("existing", version=7)
    db.save_ledger_record(existing)
    conflict = record("existing", amount="60", version=7)
    with pytest.raises(ValueError, match="旧账|baseline|冲突"):
        db.commit_plans([], [], "session-conflict", "A",
                        baseline_records=[record("new-upload"), conflict])
    assert db.get_record("new-upload", "A") is None
    assert db.get_record("existing", "A").charge_details.amount == Decimal("50")


def test_source_reuse_requires_same_processing_signature_and_record_versions(db):
    stored = record(version=7)
    db.save_ledger_record(stored)
    db.save_document_processing(b"same bill", "bill.txt", "committed",
        {"processing_signature": "sig-1", "record_versions": {stored.record_id: 7}}, "A")
    assert db.check_document_processed(b"same bill", "A", processing_signature="sig-2") is None
    assert db.check_document_processed(b"same bill", "A", processing_signature="sig-1") is not None
    stored.version = 8
    db.save_ledger_record(stored)
    assert db.check_document_processed(b"same bill", "A", processing_signature="sig-1") is None


def test_document_key_boundaries_cannot_collide(db):
    first = record("first", entity="A|B", issuer="C")
    second = record("second", entity="A", issuer="B|C")
    db.save_ledger_record(first)
    db.save_ledger_record(second)
    assert first.doc_id != second.doc_id
    assert db.get_record("first", "A|B").doc_id != db.get_record("second", "A").doc_id


def test_commit_rejects_after_record_id_different_from_plan_id(db):
    changed = plan(record("actual"))
    changed["record_id"] = "claimed"
    with pytest.raises(ValueError, match="ID|身份|record"):
        db.commit_plans([changed], [], "session-forged", "A")
    assert not db.load_ledger("A").records


def test_mysql_update_uses_atomic_version_guard(monkeypatch):
    manager = object.__new__(DatabaseManager)
    manager.db_type, manager._in_transaction = "mysql", True
    calls = []

    class Cursor:
        rowcount = 0

        def fetchone(self):
            return {"accounting_entity": "A", "version": 7}

    def execute(sql, params=()):
        calls.append((sql, params))
        return Cursor()

    monkeypatch.setattr(manager, "_execute", execute)
    monkeypatch.setattr(manager, "_ensure_document", lambda unused: "doc-1")
    with pytest.raises(ValueError, match="版本|version"):
        manager.save_ledger_record(record(version=8), expected_version=7)
    updates = [sql for sql, _ in calls if sql.lstrip().startswith("UPDATE billing_charge_lines")]
    assert updates and "version=?" in updates[-1].split("WHERE", 1)[1]


def test_mysql_current_record_read_is_locked_inside_commit(monkeypatch):
    manager = object.__new__(DatabaseManager)
    manager.db_type, manager._in_transaction, manager._legacy = "mysql", True, False
    calls = []

    class Cursor:
        def fetchone(self):
            return {"record_data": record(version=7).model_dump_json()}

    monkeypatch.setattr(manager, "_execute", lambda sql, params=(): (calls.append(sql) or Cursor()))
    assert manager.get_record("charge-1", "A", for_update=True).version == 7
    assert calls[0].rstrip().endswith("FOR UPDATE")


def test_different_source_previews_cannot_both_create_same_new_business_charge(db):
    first, second = plan(record("first")), plan(record("second"))
    db.commit_plans([first], [event(b"first scan")], "session-first", "A")
    with pytest.raises(ValueError, match="业务候选已变化"):
        db.commit_plans([second], [event(b"second scan")], "session-second", "A")
    assert [r.record_id for r in db.load_ledger("A").records] == ["first"]
    assert db.check_document_processed(b"second scan", "A") is None


def test_two_legitimate_same_name_lines_in_one_batch_are_preserved(db):
    first, second = record("first", amount="65"), record("second", amount="35")
    first.charge_details.source_line_id = "src:row-1"
    second.charge_details.source_line_id = "src:row-3"
    db.commit_plans([plan(first), plan(second)], [event()], "session-lines", "A")
    assert sorted(r.charge_details.amount for r in db.load_ledger("A").records) == [Decimal("35"), Decimal("65")]


def test_mysql_commit_scope_lock_is_acquired_with_current_read(monkeypatch):
    manager = object.__new__(DatabaseManager)
    manager.db_type, manager._in_transaction = "mysql", True
    calls = []

    class Cursor:
        def fetchone(self):
            return {"accounting_entity": "A"}

    monkeypatch.setattr(manager, "_execute", lambda sql, params=(): (calls.append((sql, params)) or Cursor()))
    manager._lock_scope("A")
    assert any("INSERT IGNORE INTO billing_scope_locks" in sql for sql, _ in calls)
    assert any("billing_scope_locks" in sql and sql.rstrip().endswith("FOR UPDATE") for sql, _ in calls)
