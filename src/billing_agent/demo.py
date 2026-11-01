"""
模拟数据生成
用于演示和测试，不依赖真实API
"""

from decimal import Decimal
from datetime import datetime

from .models import (
    AgentDecision,
    AgentDecisionBatch,
    ChargeDetails,
    DocumentInfo,
    TransactionParty,
    FinancialAttributes,
    Evidence,
    ExcludedItem,
    Ledger,
    LedgerRecord,
    AuditTrail
)


# ============================================
# 模拟旧账数据
# ============================================

def get_demo_ledger() -> Ledger:
    """获取演示用的旧账本"""

    records = [
        LedgerRecord(
            record_id="rec_001",
            charge_details=ChargeDetails(
                original_name="HANDLING CHARGE",
                standardized_name="HANDLING_CHARGE",
                amount=Decimal("50.00"),
                currency="USD",
                payment_method="PP"
            ),
            document_info=DocumentInfo(
                document_type="Debit Note",
                document_number="DN-2024-001",
                document_date="2024-01-15",
                bill_of_lading="BL123456",
                booking_number="BK789012"
            ),
            transaction_party=TransactionParty(
                issuer="ABC Shipping Co.",
                recipient="Demo Origin Corp."
            ),
            financial_attributes=FinancialAttributes(
                accounting_entity="Demo Origin",
                posting_type="AP",
                posting_type_reasoning="单据显示Demo Origin是付款方"
            ),
            audit_history=[
                AuditTrail(
                    operation_id="init_001",
                    agent_operation="CREATE",
                    agent_reasoning="初始导入",
                    agent_confidence="HIGH",
                    program_operation="CREATE",
                    validation_issues=[],
                    final_operation="CREATE",
                    conflict_resolution="初始创建"
                )
            ]
        ),
        LedgerRecord(
            record_id="rec_002",
            charge_details=ChargeDetails(
                original_name="DOCUMENTATION FEE",
                standardized_name="DOCUMENTATION_FEE",
                amount=Decimal("30.00"),
                currency="USD",
                payment_method="CC"
            ),
            document_info=DocumentInfo(
                document_type="Debit Note",
                document_number="DN-2024-001",
                document_date="2024-01-15",
                bill_of_lading="BL123456",
                booking_number="BK789012"
            ),
            transaction_party=TransactionParty(
                issuer="ABC Shipping Co.",
                recipient="Demo Origin Corp."
            ),
            financial_attributes=FinancialAttributes(
                accounting_entity="Demo Origin",
                posting_type="AP",
                posting_type_reasoning="单据显示Demo Origin是付款方"
            ),
            audit_history=[
                AuditTrail(
                    operation_id="init_002",
                    agent_operation="CREATE",
                    agent_reasoning="初始导入",
                    agent_confidence="HIGH",
                    program_operation="CREATE",
                    validation_issues=[],
                    final_operation="CREATE",
                    conflict_resolution="初始创建"
                )
            ]
        ),
        # 同名费用歧义场景：两条HANDLING CHARGE
        LedgerRecord(
            record_id="rec_003",
            charge_details=ChargeDetails(
                original_name="HANDLING CHARGE",
                standardized_name="HANDLING_CHARGE",
                amount=Decimal("65.00"),
                currency="USD",
                payment_method="PP"
            ),
            document_info=DocumentInfo(
                document_type="Debit Note",
                document_number="DN-2024-002",
                document_date="2024-01-20",
                bill_of_lading="BL654321"
            ),
            transaction_party=TransactionParty(
                issuer="ABC Shipping Co.",
                recipient="Demo Origin Corp."
            ),
            financial_attributes=FinancialAttributes(
                accounting_entity="Demo Origin",
                posting_type="AP"
            ),
            audit_history=[]
        ),
        LedgerRecord(
            record_id="rec_004",
            charge_details=ChargeDetails(
                original_name="HANDLING CHARGE",
                standardized_name="HANDLING_CHARGE",
                amount=Decimal("35.00"),
                currency="USD",
                payment_method="PP"
            ),
            document_info=DocumentInfo(
                document_type="Debit Note",
                document_number="DN-2024-002",
                document_date="2024-01-20",
                bill_of_lading="BL654321"
            ),
            transaction_party=TransactionParty(
                issuer="ABC Shipping Co.",
                recipient="Demo Origin Corp."
            ),
            financial_attributes=FinancialAttributes(
                accounting_entity="Demo Origin",
                posting_type="AP"
            ),
            audit_history=[]
        ),
    ]

    return Ledger(
        ledger_id="ledger_demo_001",
        version=1,
        accounting_entity="Demo Origin",
        records=records
    )


# ============================================
# 模拟场景1: 明确更新
# ============================================

def get_demo_scenario_update() -> AgentDecisionBatch:
    """
    场景1: 明确更新
    邮件说明：将操作费从50美元修改为40美元
    """

    decision = AgentDecision(
        suggested_operation="UPDATE",
        operation_reasoning="邮件正文明确说明'将操作费修改为40美元'，通过单据号DN-2024-001和费用名称HANDLING CHARGE唯一匹配到旧账记录rec_001",
        matched_record_id="rec_001",
        confidence="HIGH",

        charge_details=ChargeDetails(
            original_name="HANDLING CHARGE",
            standardized_name="HANDLING_CHARGE",
            amount=Decimal("40.00"),
            currency="USD",
            payment_method="PP"
        ),

        document_info=DocumentInfo(
            document_type="Debit Note",
            document_number="DN-2024-001",
            document_date="2024-01-15",
            bill_of_lading="BL123456",
            booking_number="BK789012"
        ),

        transaction_party=TransactionParty(
            issuer="ABC Shipping Co.",
            recipient="Demo Origin Corp."
        ),

        financial_attributes=FinancialAttributes(
            accounting_entity="Demo Origin",
            posting_type="AP",
            posting_type_reasoning="保持原有的付款方向"
        ),

        evidence=[
            Evidence(
                source_file="update_email.eml",
                source_type="email_body",
                location="正文第2段",
                original_text="现将单据DN-2024-001中的操作费(HANDLING CHARGE)由50美元调整为40美元。"
            )
        ],

        field_changes={
            "charge_details.amount": Decimal("40.00")
        }
    )

    return AgentDecisionBatch(
        decisions=[decision],
        excluded_items=[],
        document_summary="邮件通知修改操作费金额"
    )


# ============================================
# 模拟场景2: 同名费用歧义
# ============================================

def get_demo_scenario_ambiguous() -> AgentDecisionBatch:
    """
    场景2: 同名费用歧义
    旧账中有两条HANDLING CHARGE（65美元和35美元），无法唯一匹配
    """

    decision = AgentDecision(
        suggested_operation="UPDATE",  # 模型尝试UPDATE
        operation_reasoning="邮件提到修改HANDLING CHARGE为50美元，但旧账DN-2024-002中有两条HANDLING CHARGE（65美元和35美元），无法确定修改哪一条",
        matched_record_id=None,  # 模型无法确定
        confidence="LOW",  # 置信度低

        charge_details=ChargeDetails(
            original_name="HANDLING CHARGE",
            standardized_name="HANDLING_CHARGE",
            amount=Decimal("50.00"),
            currency="USD",
            payment_method="PP"
        ),

        document_info=DocumentInfo(
            document_type="Debit Note",
            document_number="DN-2024-002",
            document_date="2024-01-20",
            bill_of_lading="BL654321"
        ),

        transaction_party=TransactionParty(
            issuer="ABC Shipping Co.",
            recipient="Demo Origin Corp."
        ),

        financial_attributes=FinancialAttributes(
            accounting_entity="Demo Origin",
            posting_type="AP"
        ),

        evidence=[
            Evidence(
                source_file="ambiguous_email.eml",
                source_type="email_body",
                location="正文",
                original_text="请将DN-2024-002的HANDLING CHARGE调整为50美元。"
            )
        ]
    )

    return AgentDecisionBatch(
        decisions=[decision],
        excluded_items=[],
        document_summary="修改通知，但存在同名费用歧义"
    )


# ============================================
# 模拟场景3: 新增费用
# ============================================

def get_demo_scenario_create() -> AgentDecisionBatch:
    """
    场景3: 新增费用
    这是一个新的实际费用，旧账中没有对应记录
    """

    decision = AgentDecision(
        suggested_operation="CREATE",
        operation_reasoning="这是新单据DN-2024-003中的THC费用，旧账中没有该单据的记录，应创建新记录",
        matched_record_id=None,
        confidence="HIGH",

        charge_details=ChargeDetails(
            original_name="TERMINAL HANDLING CHARGE",
            standardized_name="THC",
            amount=Decimal("120.00"),
            currency="USD",
            payment_method="PP"
        ),

        document_info=DocumentInfo(
            document_type="Debit Note",
            document_number="DN-2024-003",
            document_date="2024-02-01",
            bill_of_lading="BL999888",
            booking_number="BK555666"
        ),

        transaction_party=TransactionParty(
            issuer="ABC Shipping Co.",
            recipient="Demo Origin Corp.",
            payer_description="付款方：Demo Origin Corp."
        ),

        financial_attributes=FinancialAttributes(
            accounting_entity="Demo Origin",
            posting_type="AP",
            posting_type_reasoning="单据明确标注Demo Origin为付款方"
        ),

        evidence=[
            Evidence(
                source_file="new_debit_note.pdf",
                source_type="table",
                location="费用明细表，第1行",
                original_text="TERMINAL HANDLING CHARGE: USD 120.00"
            )
        ]
    )

    return AgentDecisionBatch(
        decisions=[decision],
        excluded_items=[],
        document_summary="新增THC费用"
    )


# ============================================
# 模拟场景4: 条件收费
# ============================================

def get_demo_scenario_conditional() -> AgentDecisionBatch:
    """
    场景4: 条件收费条款
    文档中包含"如超期则收取滞期费"，这不是实际发生的费用
    """

    excluded = ExcludedItem(
        item_type="conditional_charge",
        description="滞期费（条件条款）",
        amount=Decimal("200.00"),
        currency="USD",
        reasoning="原文为'如超过免费期则收取滞期费200美元'，这是条件条款，不是实际发生的费用",
        evidence=[
            Evidence(
                source_file="contract_terms.pdf",
                source_type="text",
                location="第3页，条款说明",
                original_text="如货物在港口停留超过7天免费期，将收取滞期费USD 200.00/天。"
            )
        ]
    )

    # 实际费用（已发生）
    decision = AgentDecision(
        suggested_operation="CREATE",
        operation_reasoning="这是实际发生的仓储费，文档明确标注为'已产生费用'",
        matched_record_id=None,
        confidence="HIGH",

        charge_details=ChargeDetails(
            original_name="STORAGE FEE",
            standardized_name="STORAGE_FEE",
            amount=Decimal("150.00"),
            currency="USD",
            payment_method="PP"
        ),

        document_info=DocumentInfo(
            document_type="Invoice",
            document_number="INV-2024-100",
            document_date="2024-02-05",
            bill_of_lading="BL777888",
            container_number="CONT12345"
        ),

        transaction_party=TransactionParty(
            issuer="Port Storage Ltd.",
            recipient="Demo Origin Corp."
        ),

        financial_attributes=FinancialAttributes(
            accounting_entity="Demo Origin",
            posting_type="AP",
            posting_type_reasoning="Demo Origin为付款方"
        ),

        evidence=[
            Evidence(
                source_file="contract_terms.pdf",
                source_type="table",
                location="实际费用明细表",
                original_text="仓储费（已产生）: USD 150.00"
            )
        ]
    )

    return AgentDecisionBatch(
        decisions=[decision],
        excluded_items=[excluded],
        document_summary="包含实际费用和条件条款"
    )


# ============================================
# 获取场景
# ============================================

DEMO_SCENARIOS = {
    "update": {
        "name": "明确更新",
        "description": "将操作费从50美元修改为40美元，其他字段保留",
        "func": get_demo_scenario_update
    },
    "ambiguous": {
        "name": "同名费用歧义",
        "description": "旧账中有两条HANDLING CHARGE，无法唯一匹配",
        "func": get_demo_scenario_ambiguous
    },
    "create": {
        "name": "新增费用",
        "description": "新的THC费用，旧账中没有对应记录",
        "func": get_demo_scenario_create
    },
    "conditional": {
        "name": "条件收费",
        "description": "识别并排除条件条款，只处理实际发生的费用",
        "func": get_demo_scenario_conditional
    }
}


def get_demo_scenario(scenario_name: str) -> AgentDecisionBatch:
    """
    获取指定的演示场景

    Args:
        scenario_name: 场景名称 (update, ambiguous, create, conditional)

    Returns:
        AgentDecisionBatch
    """
    if scenario_name not in DEMO_SCENARIOS:
        raise ValueError(f"未知场景: {scenario_name}，可用场景: {list(DEMO_SCENARIOS.keys())}")

    return DEMO_SCENARIOS[scenario_name]["func"]()
