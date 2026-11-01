"""
测试数据模型
"""

import pytest
from decimal import Decimal
from src.billing_agent.models import (
    ChargeDetails,
    DocumentInfo,
    Evidence,
    AgentDecision,
    ValidationResult,
    FinancialAttributes
)


def test_charge_details_creation():
    """测试费用详情创建"""
    charge = ChargeDetails(
        original_name="HANDLING CHARGE",
        standardized_name="HANDLING_CHARGE",
        amount=Decimal("50.00"),
        currency="USD",
        payment_method="PP"
    )

    assert charge.original_name == "HANDLING CHARGE"
    assert charge.amount == Decimal("50.00")
    assert charge.currency == "USD"


def test_charge_details_decimal_conversion():
    """测试金额的Decimal转换"""
    charge = ChargeDetails(
        original_name="TEST",
        amount="123.45",  # 字符串
        currency="USD"
    )

    assert isinstance(charge.amount, Decimal)
    assert charge.amount == Decimal("123.45")


def test_agent_decision_creation():
    """测试Agent决策创建"""
    decision = AgentDecision(
        suggested_operation="CREATE",
        operation_reasoning="这是新费用",
        confidence="HIGH",
        charge_details=ChargeDetails(
            original_name="TEST",
            amount=Decimal("100.00"),
            currency="USD"
        ),
        document_info=DocumentInfo(),
        transaction_party={"issuer": None, "recipient": None},
        financial_attributes=FinancialAttributes(
            accounting_entity="Test Entity"
        ),
        evidence=[]
    )

    assert decision.suggested_operation == "CREATE"
    assert decision.confidence == "HIGH"


def test_validation_result():
    """测试验证结果"""
    result = ValidationResult(
        is_valid=False,
        program_operation="PENDING_REVIEW",
        validation_issues=["金额格式错误"]
    )

    assert not result.is_valid
    assert len(result.validation_issues) == 1
