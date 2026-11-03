"""
测试框架 - 单元测试
测试 Agent 提取功能
"""

import pytest
from decimal import Decimal
from src.billing_agent.agent import parse_agent_response
from src.billing_agent.models import AgentDecisionBatch


class TestAgentExtraction:
    """测试 Agent 提取功能"""

    def test_extract_simple_charge(self):
        """测试提取简单费用"""
        response = {
            "decisions": [{
                "charge_details": {
                    "original_name": "HANDLING CHARGE",
                    "amount": 65.00,
                    "currency": "USD"
                },
                "document_info": {
                    "document_number": "DC-108478"
                },
                "transaction_party": {},
                "financial_attributes": {
                    "posting_type": "AR"
                },
                "evidence": [{
                    "source_file": "test.pdf",
                    "source_type": "attachment",
                    "original_text": "HANDLING CHARGE 65.00"
                }]
            }],
            "excluded_items": []
        }

        batch = parse_agent_response(response, "Test Company")

        assert len(batch.decisions) == 1
        decision = batch.decisions[0]
        assert decision.charge_details.original_name == "HANDLING CHARGE"
        assert decision.charge_details.amount == Decimal("65.00")
        assert decision.charge_details.currency == "USD"
        assert decision.document_info.document_number == "DC-108478"

    def test_extract_with_line_items(self):
        """测试提取带明细项的账单"""
        response = {
            "decisions": [{
                "charge_details": {
                    "original_name": "DEBIT NOTE",
                    "amount": 1420.40,
                    "currency": "USD",
                    "line_items": [
                        {"description": "HANDLING CHARGE", "amount": 65.00, "currency": "USD"},
                        {"description": "DETENTION CHARGE", "amount": 1310.40, "currency": "USD"},
                        {"description": "HANDLING CHARGE", "amount": 45.00, "currency": "USD"}
                    ]
                },
                "document_info": {
                    "document_number": "DC-108478"
                },
                "transaction_party": {},
                "financial_attributes": {
                    "posting_type": "AR"
                },
                "evidence": [{
                    "source_file": "test.pdf",
                    "source_type": "attachment",
                    "original_text": "TOTAL 1420.40 USD"
                }]
            }],
            "excluded_items": []
        }

        batch = parse_agent_response(response, "Test Company")

        assert len(batch.decisions) == 1
        decision = batch.decisions[0]
        assert decision.charge_details.amount == Decimal("1420.40")
        assert len(decision.charge_details.line_items) == 3

        # 验证明细项总和
        total = sum(item.amount for item in decision.charge_details.line_items)
        assert total == Decimal("1420.40")

    def test_missing_currency_stays_unknown(self):
        """公司未返回币种时保留未知，由人工核对。"""
        response = {
            "decisions": [{
                "charge_details": {
                    "original_name": "FREIGHT CHARGE",
                    "amount": 100.00
                    # 缺少 currency
                },
                "document_info": {},
                "transaction_party": {},
                "financial_attributes": {},
                "evidence": [{
                    "source_file": "test.pdf",
                    "source_type": "attachment",
                    "original_text": "FREIGHT 100.00"
                }]
            }],
            "excluded_items": []
        }

        batch = parse_agent_response(response, "Test Company")

        # 用户已确认：缺失币种不能无依据默认成 USD。
        assert batch.decisions[0].charge_details.currency is None

    def test_skip_invalid_decision(self):
        """测试跳过无效决策"""
        response = {
            "decisions": [
                {
                    # 缺少 original_name
                    "charge_details": {
                        "amount": 100.00,
                        "currency": "USD"
                    },
                    "document_info": {},
                    "transaction_party": {},
                    "financial_attributes": {},
                    "evidence": []
                },
                {
                    # 有效决策
                    "charge_details": {
                        "original_name": "VALID CHARGE",
                        "amount": 200.00,
                        "currency": "USD"
                    },
                    "document_info": {},
                    "transaction_party": {},
                    "financial_attributes": {},
                    "evidence": [{
                        "source_file": "test.pdf",
                        "source_type": "attachment",
                        "original_text": "VALID 200"
                    }]
                }
            ],
            "excluded_items": []
        }

        batch = parse_agent_response(response, "Test Company")

        # 应该只有1个有效决策
        assert len(batch.decisions) == 1
        assert batch.decisions[0].charge_details.original_name == "VALID CHARGE"


class TestAmountParsing:
    """测试金额解析"""

    def test_parse_decimal_with_comma(self):
        """测试带逗号的金额"""
        response = {
            "decisions": [{
                "charge_details": {
                    "original_name": "FREIGHT",
                    "amount": "1,234.56",  # 字符串格式
                    "currency": "USD"
                },
                "document_info": {},
                "transaction_party": {},
                "financial_attributes": {},
                "evidence": [{
                    "source_file": "test.pdf",
                    "source_type": "attachment",
                    "original_text": "1,234.56"
                }]
            }],
            "excluded_items": []
        }

        batch = parse_agent_response(response, "Test Company")

        # 逗号应该被移除
        assert batch.decisions[0].charge_details.amount == Decimal("1234.56")

    def test_parse_integer_amount(self):
        """测试整数金额"""
        response = {
            "decisions": [{
                "charge_details": {
                    "original_name": "FREIGHT",
                    "amount": 1000,  # 整数
                    "currency": "USD"
                },
                "document_info": {},
                "transaction_party": {},
                "financial_attributes": {},
                "evidence": [{
                    "source_file": "test.pdf",
                    "source_type": "attachment",
                    "original_text": "1000"
                }]
            }],
            "excluded_items": []
        }

        batch = parse_agent_response(response, "Test Company")

        assert batch.decisions[0].charge_details.amount == Decimal("1000")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
