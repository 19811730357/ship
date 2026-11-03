"""A source total cannot masquerade as the amount of a fee."""
from decimal import Decimal
from pathlib import Path

import pytest

from src.billing_agent.models import AgentDecisionBatch, Evidence
from src.billing_agent.validator import validate_extracted_charge
from .test_safe_billing import make_decision
from .test_safe_workflow import engine


def sources(line="300", total="245", total_text=None):
    blocks = [
        {"source_id": "src-1", "block_id": "identity", "page": 1, "text": "INV-1 Issuer"},
        {"source_id": "src-1", "block_id": "fee", "page": 1, "text": f"HANDLING USD {line}"},
        {"source_id": "src-1", "block_id": "total", "page": 1,
         "text": total_text or f"TOTAL CHARGES TO BE PAID: USD {total}"},
    ]
    return [{"source_id": "src-1", "source_file": "bill.txt", "blocks": blocks,
             "content": "\n".join(b["text"] for b in blocks)}]


def decision(amount="300", total="245", evidence_block="fee", data=None):
    item = make_decision(amount)
    item.document_info.document_total = Decimal(total) if total is not None else None
    item.document_info.total_currency = "USD" if total is not None else None
    material = data or sources()
    block = next(b for b in material[0]["blocks"] if b["block_id"] == evidence_block)
    item.evidence = [Evidence(source_id="src-1", source_file="bill.txt", source_type="text",
                              block_id=evidence_block, page=1,
                              field_name="charge_details.amount", original_text=block["text"])]
    return item


def preview_and_commit(item, material):
    flow = engine([item])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[item]), material)
    result = flow.commit_preview(preview["preview_id"])
    records = flow.db.load_ledger("A").records
    flow.close()
    return preview, result, records


def test_wrong_245_from_total_cannot_create_when_source_fee_is_300():
    material = sources()
    item = decision("245", "245", "total", material)
    preview, result, records = preview_and_commit(item, material)
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert records == []
    assert not result["committed"]


def test_source_total_missing_in_model_does_not_skip_reconciliation():
    preview, _, records = preview_and_commit(decision(total=None), sources())
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert any("总额" in issue for issue in preview["run_report"]["document_issues"])
    assert not records


def test_source_mismatch_reports_both_amounts_and_difference():
    preview, _, records = preview_and_commit(decision(), sources())
    text = " ".join(preview["run_report"]["document_issues"])
    assert "300" in text and "245" in text and "55" in text
    assert not records


def test_manual_amount_cannot_hide_an_unreconciled_source_fee():
    item = decision()
    flow = engine([item])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[item]), sources())
    result = flow.commit_preview(preview["preview_id"], {"0": {
        "approve_create": True, "amount": "245", "note": "确认通过"}})
    assert not result["committed"]
    assert flow.db.load_ledger("A").records == []
    assert any("300" in issue for issue in result["processing_results"][0]["validation_issues"])
    flow.close()


def test_correct_fee_and_source_total_can_commit():
    material = sources("245", "245")
    preview, result, records = preview_and_commit(decision("245", "245", data=material), material)
    assert preview["summary"]["operations"]["CREATE"] == 1
    assert result["committed"]
    assert records[0].charge_details.amount == Decimal("245")


def test_total_quote_is_not_line_evidence_even_when_values_are_equal():
    material = sources("245", "245")
    item = decision("245", "245", "total", material)
    assert validate_extracted_charge(item, material)


def test_source_total_glued_to_date_preserves_four_decimal_amount():
    material = sources("245", "245", "LBSTOTAL CHARGES TO BE PAID: 245.000010/19/2026 05:58 PM")
    preview, result, _ = preview_and_commit(decision("245", "245", data=material), material)
    assert preview["run_report"]["document_issues"] == []
    assert result["committed"]


@pytest.mark.parametrize("label", ["SUBTOTAL", "BALANCE DUE", "UNIT PRICE", "EXCHANGE RATE"])
def test_summary_and_rate_rows_cannot_support_a_line_amount(label):
    material = sources("245", "245", f"{label}: USD 245")
    item = decision("245", None, "total", material)
    assert validate_extracted_charge(item, material)


def test_an_unassigned_total_on_another_page_requires_review():
    material = sources("245", "245")
    material[0]["blocks"].append({"source_id": "src-1", "block_id": "other-total", "page": 2,
                                    "text": "TOTAL CHARGES TO BE PAID: USD 999"})
    material[0]["content"] += "\nTOTAL CHARGES TO BE PAID: USD 999"
    preview, result, _ = preview_and_commit(decision("245", "245", data=material), material)
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert not result["committed"]


def test_total_on_following_page_is_not_missed_when_model_omits_it():
    material = sources()
    material[0]["blocks"][-1]["page"] = 2
    preview, result, records = preview_and_commit(decision(total=None, data=material), material)
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert not result["committed"] and not records


@pytest.mark.parametrize("label", ["SUB TOTAL", "TOTAL WEIGHT", "TOTAL QUANTITY", "TOTAL PACKAGES"])
def test_non_document_totals_are_not_document_total_candidates(label):
    from src.billing_agent.source_amounts import source_totals
    assert source_totals(sources(total_text=f"{label}: 999 KGS")[0]) == []


def test_quantity_in_an_unlabelled_multi_number_row_is_not_an_amount():
    material = sources()
    material[0]["blocks"] = material[0]["blocks"][:2]
    material[0]["blocks"][1]["text"] = "HANDLING 2 5.00 USD 10.00"
    material[0]["content"] = "INV-1 Issuer\nHANDLING 2 5.00 USD 10.00"
    item = decision("2", None, data=material)
    preview, result, records = preview_and_commit(item, material)
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert not result["committed"] and not records


def test_markdown_amount_header_resolves_quantity_and_unit_price_columns():
    material = sources()
    material[0]["blocks"] = [material[0]["blocks"][0],
        {"source_id": "src-1", "block_id": "header", "page": 1,
         "text": "| Fee | Quantity | Unit Price | Currency | Amount |"},
        {"source_id": "src-1", "block_id": "fee", "page": 1,
         "text": "| HANDLING | 2 | 5.00 | USD | 10.00 |"}]
    material[0]["content"] = "\n".join(b["text"] for b in material[0]["blocks"])
    item = decision("10", None, data=material)
    preview, result, records = preview_and_commit(item, material)
    assert preview["summary"]["operations"]["CREATE"] == 1
    assert result["committed"] and records[0].charge_details.amount == Decimal("10")


def test_multi_currency_total_is_not_silently_reduced_to_first_number():
    material = sources("10", "10", "TOTAL USD 10 CNY 70")
    preview, result, _ = preview_and_commit(decision("10", "10", data=material), material)
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert not result["committed"]


def test_two_invoices_in_one_pdf_keep_their_following_page_totals_separate():
    from src.billing_agent.models import Evidence
    material = sources("40", "40")
    material[0]["blocks"][-1]["page"] = 2
    material[0]["blocks"].extend([
        {"source_id": "src-1", "block_id": "identity-2", "page": 3, "text": "INV-2 Issuer"},
        {"source_id": "src-1", "block_id": "fee-2", "page": 3, "text": "HANDLING USD 60"},
        {"source_id": "src-1", "block_id": "total-2", "page": 3, "text": "TOTAL CHARGES TO BE PAID: USD 60"},
    ])
    material[0]["content"] = "\n".join(b["text"] for b in material[0]["blocks"])
    first = decision("40", "40", data=material)
    second = make_decision("60", number="INV-2")
    second.document_info.document_total = Decimal("60")
    second.document_info.total_currency = "USD"
    second.evidence = [Evidence(source_id="src-1", source_file="bill.txt", source_type="pdf", page=3,
        block_id="fee-2", field_name="charge_details.amount", original_text="HANDLING USD 60")]
    flow = engine([first, second])
    preview = flow.prepare_batch(AgentDecisionBatch(decisions=[first, second]), material)
    assert preview["summary"]["operations"]["CREATE"] == 2
    assert flow.commit_preview(preview["preview_id"])["committed"]
    assert len(flow.db.load_ledger("A").records) == 2
    flow.close()


def test_real_modified_pdf_reports_300_245_difference_55():
    from src.billing_agent.parsers import DocumentParser
    from src.billing_agent.workflow_db import DatabaseWorkflow
    path = Path(__file__).resolve().parents[2] / "笔试题AIAGENT" / "PDF示例账单1.1.pdf"
    if not path.exists():
        pytest.skip("user-provided modified PDF is not available")
    parsed = DocumentParser().parse_file(path)
    material = DatabaseWorkflow._source_views(parsed)
    block = next(b for s in material for b in s["blocks"] if b["text"].strip() == "300.0000")
    item = make_decision("300")
    item.document_info.document_number = "CHN4053601"
    item.transaction_party.issuer = "NEPTUNE SHIPPING LIMITED"
    item.charge_details.original_name = "On Carriage Additional - US Em OCA17"
    item.charge_details.standardized_name = None
    item.document_info.document_total = Decimal("245")
    item.document_info.total_currency = "USD"
    item.evidence = [Evidence(source_file=parsed["source_file"], source_type="pdf", source_id=parsed["source_id"],
        block_id=block["block_id"], original_text=block["text"], page=1, field_name="charge_details.amount")]
    preview, result, records = preview_and_commit(item, material)
    text = " ".join(preview["run_report"]["document_issues"])
    assert all(value in text for value in ("300", "245", "55"))
    assert not result["committed"] and not records


def test_real_modified_pdf_300_245_cannot_commit_total_as_fee():
    from src.billing_agent.parsers import DocumentParser
    from src.billing_agent.workflow_db import DatabaseWorkflow
    path = Path(__file__).resolve().parents[2] / "笔试题AIAGENT" / "PDF示例账单1.1.pdf"
    if not path.exists():
        pytest.skip("user-provided modified PDF is not available")
    parsed = DocumentParser().parse_file(path)
    material = DatabaseWorkflow._source_views(parsed)
    block = next(b for s in material for b in s["blocks"] if "TOTAL CHARGES TO BE PAID" in b["text"])
    item = make_decision("245")
    item.document_info.document_number = "CHN4053601"
    item.transaction_party.issuer = "NEPTUNE SHIPPING LIMITED"
    item.charge_details.original_name = "On Carriage Additional - US Em OCA17"
    item.charge_details.standardized_name = None
    item.document_info.document_total = Decimal("245")
    item.document_info.total_currency = "USD"
    item.evidence = [Evidence(source_file=parsed["source_file"], source_type="pdf", source_id=parsed["source_id"],
        block_id=block["block_id"], original_text=block["text"], page=1, field_name="charge_details.amount")]
    preview, _, records = preview_and_commit(item, material)
    assert preview["summary"]["operations"]["PENDING_REVIEW"] == 1
    assert not records
    assert any("明细" in issue or "总额" in issue for issue in preview["processing_results"][0]["validation_issues"])
