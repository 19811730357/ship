"""Offline acceptance using real sources and explicitly synthetic extraction context.

These tests do NOT measure LLM/OCR accuracy or adjudicate actual AR/AP parties.
Only the numeric facts, raw labels and source locations come from the supplied PDF.
AP direction and the detention code are approved fixture assumptions used to test
the downstream persistence contract. No external services are called.
"""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import tempfile

import pytest

from src.billing_agent.database import DatabaseManager
from src.billing_agent.models import (
    AgentDecision, AgentDecisionBatch, ChargeDetails, DocumentInfo, Evidence,
    FinancialAttributes, TransactionParty,
)
from src.billing_agent.parsers import DocumentParser
from src.billing_agent.runtime import OUTPUT_DIR
from src.billing_agent.workflow_db import DatabaseWorkflow


SAMPLES = Path(__file__).resolve().parents[2] / "笔试题AIAGENT"
PDF2 = SAMPLES / "PDF 示例账单2.pdf"
SYNTHETIC_ENTITY = "OFFLINE-ACCEPTANCE-SYNTHETIC-PAYER"
FIXTURE_NOTICE = (
    "离线验收合成上下文：仅为验证处理链路，预设测试账套为付款方(AP)，"
    "并批准DETENTION_FREE_TIME_CHARGE映射；不代表真实交易方向或真实模型判断。"
)


@pytest.fixture
def work():
    directory = OUTPUT_DIR / "test-temp"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as folder:
        yield Path(folder)


def block_containing(parsed, marker):
    return next(block for block in parsed["blocks"] if marker in block["text"])


def proof(parsed, block, field):
    return Evidence(
        source_file=parsed["source_file"], source_type="pdf",
        source_id=parsed["source_id"], source_version=parsed["source_id"],
        block_id=block["block_id"], original_text=block["text"],
        page=block.get("page"), row=block.get("row"), location=block["location"],
        field_name=field,
    )


def frozen_pdf2_batch(parsed):
    """Human-frozen extraction facts; never calls a model or invents a row number."""
    number = block_containing(parsed, "D/C No. : DC-108478")
    issuer = block_containing(parsed, "Pilot Aiship Tech co., Ltd.")
    total = block_containing(parsed, "TOTAL AMOUNT 1,410.40")
    master = block_containing(parsed, "MASTER B/L NO. :MAEU275752922")
    house = block_containing(parsed, "HOUSE B/L NO. : CGT260801188")
    rows = [
        ("HANDLING CHARGE - 65.00", "HANDLING CHARGE", "HANDLING_CHARGE", Decimal("65.00")),
        ("4 ADD'L DETENTION FREE TIME CHARGE - 1,310.40",
         "4 ADD'L DETENTION FREE TIME CHARGE", "DETENTION_FREE_TIME_CHARGE", Decimal("1310.40")),
        ("HANDLING CHARGE - 35.00", "HANDLING CHARGE", "HANDLING_CHARGE", Decimal("35.00")),
    ]
    decisions = []
    for marker, raw_name, code, amount in rows:
        row = block_containing(parsed, marker)
        decisions.append(AgentDecision(
            suggested_operation="CREATE", confidence="HIGH",
            operation_reasoning="Frozen offline extraction fixture; " + FIXTURE_NOTICE,
            charge_details=ChargeDetails(
                original_name=raw_name, standardized_name=code, amount=amount, currency="USD",
                amount_role="line_amount", quantity=Decimal("1.00"), unit_price=amount,
                source_line_id=row["block_id"],
            ),
            document_info=DocumentInfo(
                document_type="DEBIT_NOTE", document_number="DC-108478",
                master_bill_of_lading="MAEU275752922", house_bill_of_lading="CGT260801188",
                container_numbers=["MRSU2571577", "TCLU8619685"],
                document_total=Decimal("1410.40"), total_currency="USD",
                paid_amount=Decimal("0.00"), balance_due=Decimal("1410.40"),
            ),
            transaction_party=TransactionParty(issuer="Pilot Aiship Tech co., Ltd."),
            financial_attributes=FinancialAttributes(
                accounting_entity=SYNTHETIC_ENTITY, posting_type="AP",
                posting_type_reasoning=FIXTURE_NOTICE,
            ),
            evidence=[proof(parsed, row, "charge_details.amount"),
                      proof(parsed, number, "document_info.document_number"),
                      proof(parsed, issuer, "transaction_party.issuer"),
                      proof(parsed, total, "document_info.document_total"),
                      proof(parsed, master, "document_info.master_bill_of_lading"),
                      proof(parsed, house, "document_info.house_bill_of_lading")],
        ))
    return AgentDecisionBatch(decisions=decisions, processing_metadata={
        "mode": "offline_frozen_extraction", "synthetic_context": FIXTURE_NOTICE,
        "live_model_accuracy_evaluated": False, "live_ocr_evaluated": False,
    })


class FrozenAgent:
    def __init__(self, batch):
        self.batch = batch
        self.calls = 0

    def process_material(self, text, ledger):
        self.calls += 1
        assert "source_id=" in text and "block_id=" in text
        return self.batch.model_copy(deep=True)


def test_real_pdf2_three_independent_charges_commit_without_total_duplication(work):
    assert PDF2.is_file(), "Supplied PDF2 fixture is missing"
    parser = DocumentParser(work_dir=work)
    parsed = parser.parse_file(PDF2)
    assert parsed["errors"] == []
    assert parsed["source_id"] == "70dcc3e7d07a0012fc642af256371f25438eed2c7bbe25442b7ffbd193fd34ba"
    batch = frozen_pdf2_batch(parsed)
    agent = FrozenAgent(batch)
    db = DatabaseManager("sqlite", {"database": ":memory:"})
    try:
        flow = DatabaseWorkflow(SYNTHETIC_ENTITY, db_manager=db, agent=agent, parser=parser)
        preview = flow.process_real_files([PDF2])
        assert preview["summary"]["operations"]["CREATE"] == 3
        assert preview["summary"]["operations"]["PENDING_REVIEW"] == 0
        assert db.load_ledger(SYNTHETIC_ENTITY).records == []
        result = flow.commit_preview(preview["preview_id"])
        assert result["committed"] is True
        records = db.load_ledger(SYNTHETIC_ENTITY).records
        assert len(records) == 3
        assert len({record.record_id for record in records}) == 3
        assert len({record.doc_id for record in records}) == 1
        assert Counter(record.charge_details.original_name for record in records)["HANDLING CHARGE"] == 2
        assert sorted(record.charge_details.amount for record in records) == [
            Decimal("35.00"), Decimal("65.00"), Decimal("1310.40")]
        assert sum((record.charge_details.amount for record in records), Decimal("0")) == Decimal("1410.40")
        assert all(record.charge_details.amount_role == "line_amount" for record in records)
        assert all(record.charge_details.amount != Decimal("1410.40") for record in records)
        assert all(record.document_info.document_total == Decimal("1410.40") for record in records)
        assert all(record.evidence[0].source_id == parsed["source_id"] for record in records)
        assert len({record.charge_details.source_line_id for record in records}) == 3
        replay = flow.process_real_files([PDF2])
        assert replay["run_report"]["files_skipped"] == 1
        assert replay["summary"]["operations"]["CREATE"] == 0
        assert len(db.load_ledger(SYNTHETIC_ENTITY).records) == 3
        assert agent.calls == 1
    finally:
        db.close()


def test_real_eml_includes_attached_bills_and_reports_unreviewed_inline_image(work):
    email_path = next(SAMPLES.glob("*.eml"))
    # Disable the reviewed-asset catalog to keep exercising unknown-image
    # failures: a known banner's review must not hide other parser errors.
    parser = DocumentParser(work_dir=work, non_billing_assets={})
    parsed = parser.parse_file(email_path)
    pdf_attachments = [a for a in parsed["attachments"] if a["filename"].lower().endswith(".pdf")]
    assert len(pdf_attachments) == 2
    assert all(attachment["status"] == "success" for attachment in pdf_attachments)
    assert all(attachment["parent_source_id"] == parsed["source_id"] for attachment in pdf_attachments)
    assert "OOLU4055331281" in parsed["content"]
    assert "SSZSE26093128" in parsed["content"]
    assert "TIIU8975975" in parsed["content"]
    assert all(attachment["parsed"]["blocks"] for attachment in pdf_attachments)
    image = next(a for a in parsed["attachments"] if a["filename"] == "InsertPic_C25B.jpg")
    assert image["status"] == "failed"
    assert any(error["filename"] == image["filename"] for error in parsed["errors"])

    # A frozen USD assumption here is only a fixture used to verify that a parser
    # issue blocks writes; the email's bare '$' does not establish real currency.
    row = block_containing(parsed, "H/C $50")
    decision = AgentDecision(
        suggested_operation="CREATE", operation_reasoning=FIXTURE_NOTICE, confidence="HIGH",
        charge_details=ChargeDetails(original_name="H/C", standardized_name="HANDLING_CHARGE",
                                     amount=Decimal("50"), currency="USD", source_line_id=row["block_id"]),
        document_info=DocumentInfo(document_type="EMAIL_NOTICE", document_number="SSZSE26093128"),
        transaction_party=TransactionParty(issuer="SYNTHETIC-ISSUER-FOR-BLOCKING-TEST"),
        financial_attributes=FinancialAttributes(accounting_entity=SYNTHETIC_ENTITY, posting_type="AP",
                                                posting_type_reasoning=FIXTURE_NOTICE),
        evidence=[proof(parsed, row, "charge_details.amount")],
    )
    db = DatabaseManager("sqlite", {"database": ":memory:"})
    try:
        flow = DatabaseWorkflow(SYNTHETIC_ENTITY, db_manager=db,
                                agent=FrozenAgent(AgentDecisionBatch(decisions=[decision])), parser=parser)
        preview = flow.process_real_files([email_path])
        assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
        issue = next(e for e in preview["run_report"]["file_errors"] if e.get("filename") == "InsertPic_C25B.jpg")
        assert issue["origin"] == "parser" and issue["reviewable"] is True
        result = flow.commit_preview(preview["preview_id"])
        assert result["committed"] is False
        assert db.load_ledger(SYNTHETIC_ENTITY).records == []
        assert db.check_document_processed(email_path.read_bytes(), SYNTHETIC_ENTITY) is None
    finally:
        db.close()


def test_real_eml_skips_only_the_reviewed_banner_and_keeps_attachment_observation(work):
    parsed = DocumentParser(work_dir=work).parse_file(next(SAMPLES.glob("*.eml")))
    banner = next(a for a in parsed["attachments"] if a["filename"] == "InsertPic_C25B.jpg")
    assert banner["status"] == "skipped"
    assert banner["parsed"]["metadata"]["asset_review"]["scope"] == "email_attachment"
    assert Path(banner["parsed"]["metadata"]["observation_path"]).is_file()
    assert not any(error.get("severity") != "warning" for error in parsed["errors"])
