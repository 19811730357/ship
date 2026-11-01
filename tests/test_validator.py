"""
测试验证器
"""

import pytest
from decimal import Decimal

from src.billing_agent.models import (
    AgentDecision,
    ChargeDetails,
    DocumentInfo,
    TransactionParty,
    FinancialAttributes,
    Ledger,
    LedgerRecord
)
from src.billing_agent.validator import Validator, standardize_charge_name, standardize_currency


def test_standardize_charge_name():
    """测试费用名称标准化"""
    assert standardize_charge_name("handling charge") == "HANDLING_CHARGE"
    assert standardize_charge_name("HANDLING") == "HANDLING_CHARGE"
    assert standardize_charge_name("操作费") == "HANDLING_CHARGE"
    assert standardize_charge_name("unknown charge") is None


def test_standardize_currency():
    """测试币种标准化"""
    assert standardize_currency("usd") == "USD"
    assert standardize_currency("dollar") == "USD"
    assert standardize_currency("$") == "USD"
    assert standardize_currency("rmb") == "CNY"
    assert standardize_currency("EUR") == "EUR"


def test_validator_basic_fields():
    """测试基础字段验证"""
    validator = Validator(accounting_entity="Test Entity")

    # 创建有效的决策
    decision = AgentDecision(
        suggested_operation="CREATE",
        operation_reasoning="Test",
        confidence="HIGH",
        charge_details=ChargeDetails(
            original_name="TEST CHARGE",
            amount=Decimal("100.00"),
            currency="USD"
        ),
        document_info=DocumentInfo(),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(
            accounting_entity="Test Entity"
        )
    )

    ledger = Ledger(accounting_entity="Test Entity")
    result = validator.validate_decision(decision, ledger)

    # 应该通过验证
    assert result.is_valid
    assert len(result.validation_issues) == 0


def test_validator_invalid_amount():
    """测试无效金额"""
    validator = Validator(accounting_entity="Test Entity")

    decision = AgentDecision(
        suggested_operation="CREATE",
        operation_reasoning="Test",
        confidence="HIGH",
        charge_details=ChargeDetails(
            original_name="TEST",
            amount=Decimal("-100.00"),  # 负金额
            currency="USD"
        ),
        document_info=DocumentInfo(),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(
            accounting_entity="Test Entity"
        )
    )

    ledger = Ledger(accounting_entity="Test Entity")
    result = validator.validate_decision(decision, ledger)

    # 应该失败
    assert not result.is_valid
    assert any("金额必须大于0" in issue for issue in result.validation_issues)


def test_validator_entity_mismatch():
    """测试记账主体不一致"""
    validator = Validator(accounting_entity="Entity A")

    decision = AgentDecision(
        suggested_operation="CREATE",
        operation_reasoning="Test",
        confidence="HIGH",
        charge_details=ChargeDetails(
            original_name="TEST",
            amount=Decimal("100.00"),
            currency="USD"
        ),
        document_info=DocumentInfo(),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(
            accounting_entity="Entity B"  # 不同的主体
        )
    )

    ledger = Ledger(accounting_entity="Entity A")
    result = validator.validate_decision(decision, ledger)

    # 应该失败
    assert not result.is_valid
    assert any("记账主体不一致" in issue for issue in result.validation_issues)


def test_validator_match_by_document_number():
    """测试按单据号匹配"""
    validator = Validator(accounting_entity="Test Entity")

    # 创建旧账
    old_record = LedgerRecord(
        record_id="rec_001",
        charge_details=ChargeDetails(
            original_name="HANDLING CHARGE",
            standardized_name="HANDLING_CHARGE",
            amount=Decimal("50.00"),
            currency="USD"
        ),
        document_info=DocumentInfo(
            document_number="DN-001"
        ),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(
            accounting_entity="Test Entity"
        )
    )

    ledger = Ledger(
        accounting_entity="Test Entity",
        records=[old_record]
    )

    # 创建匹配的决策
    decision = AgentDecision(
        suggested_operation="UPDATE",
        operation_reasoning="Test",
        matched_record_id="rec_001",
        confidence="HIGH",
        charge_details=ChargeDetails(
            original_name="HANDLING CHARGE",
            standardized_name="HANDLING_CHARGE",
            amount=Decimal("40.00"),
            currency="USD"
        ),
        document_info=DocumentInfo(
            document_number="DN-001"
        ),
        transaction_party=TransactionParty(),
        financial_attributes=FinancialAttributes(
            accounting_entity="Test Entity"
        )
    )

    result = validator.validate_decision(decision, ledger)

    # 应该通过验证，且程序也找到匹配
    assert result.program_operation == "UPDATE"
    assert result.program_matched_record_id == "rec_001"
