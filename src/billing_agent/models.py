"""
数据模型定义
使用Pydantic V2进行数据验证和序列化
"""

from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from decimal import Decimal
import uuid


# ============================================
# 基础数据类型
# ============================================

class Evidence(BaseModel):
    """证据信息"""
    source_file: str = Field(description="来源文件名")
    source_type: str = Field(description="来源类型：email_body, attachment, table等")
    location: Optional[str] = Field(None, description="位置信息：页码、行号、工作表等")
    original_text: str = Field(description="原文引用")
    source_id: Optional[str] = Field(None, description="解析器给出的不可变来源ID")
    source_version: Optional[str] = Field(None, description="来源文件版本或摘要")
    block_id: Optional[str] = Field(None, description="解析器给出的原文块ID")
    page: Optional[int] = None
    row: Optional[int] = None
    column: Optional[int | str] = None
    field_name: Optional[str] = Field(None, description="证据支持的标准字段路径")
    extraction_timestamp: datetime = Field(default_factory=datetime.now)


class DocumentInfo(BaseModel):
    """单据信息"""
    document_type: Optional[str] = Field(None, description="单据类型：Debit Note, Credit Note等")
    document_number: Optional[str] = Field(None, description="单据编号")
    document_date: Optional[str] = Field(None, description="单据日期")
    bill_of_lading: Optional[str] = Field(None, description="提单号")
    booking_number: Optional[str] = Field(None, description="订舱号")
    container_number: Optional[str] = Field(None, description="箱号")
    master_bill_of_lading: Optional[str] = None
    house_bill_of_lading: Optional[str] = None
    container_numbers: List[str] = Field(default_factory=list)
    document_total: Optional[Decimal] = Field(None, description="原单明示总额，不是当前费用计算值")
    total_currency: Optional[str] = None
    paid_amount: Optional[Decimal] = None
    balance_due: Optional[Decimal] = None


class TransactionParty(BaseModel):
    """交易方信息"""
    issuer: Optional[str] = Field(None, description="单据签发方")
    recipient: Optional[str] = Field(None, description="账单接收方")
    payer_description: Optional[str] = Field(None, description="付款方描述原文")


class LineItem(BaseModel):
    """账单明细项"""
    description: str = Field(description="明细项描述")
    amount: Decimal = Field(description="金额")
    currency: str = Field(description="币种")
    quantity: Optional[Decimal] = Field(None, description="数量")
    unit_price: Optional[Decimal] = Field(None, description="单价")

    @field_validator('amount', 'quantity', 'unit_price', mode='before')
    @classmethod
    def validate_decimal(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class ChargeDetails(BaseModel):
    """费用详情"""
    original_name: str = Field(description="原始费用名称")
    standardized_name: Optional[str] = Field(None, description="标准化费用名称")
    quantity: Optional[Decimal] = Field(None, description="数量")
    unit_price: Optional[Decimal] = Field(None, description="单价")
    amount: Decimal = Field(description="本条费用的原币金额，保留原文符号和精度")
    currency: Optional[str] = Field(None, description="明确的ISO 4217代码，币种未知时为null")
    amount_role: Literal[
        "line_amount", "document_total", "subtotal", "unit_price", "settlement_amount",
        "paid_amount", "balance_due", "conditional_rate", "exchange_rate"
    ] = "line_amount"
    source_line_id: Optional[str] = Field(None, description="本次来源中的费用行定位，不能跨版本当作费用身份")
    line_reference: Optional[str] = Field(None, description="单据明示且可跨版本核对的费用行编号")
    service_scope: Optional[str] = Field(None, description="原文明示的服务或计费范围")
    settlement_amount: Optional[Decimal] = None
    settlement_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = Field(None, description="原文明示的汇率，不自行推算")
    payment_method: Optional[str] = Field(None, description="付款方式：PP, CC等")
    line_items: Optional[List['LineItem']] = Field(None, description="账单明细项列表")

    @field_validator('amount', 'quantity', 'unit_price', 'settlement_amount', 'exchange_rate', mode='before')
    @classmethod
    def validate_decimal(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float, str)):
            return Decimal(str(v))
        return v


class FinancialAttributes(BaseModel):
    """财务属性"""
    accounting_entity: str = Field(description="记账主体")
    posting_type: Optional[Literal["AR", "AP"]] = Field(None, description="应收或应付")
    posting_type_reasoning: Optional[str] = Field(None, description="判断依据")


# ============================================
# Agent决策相关
# ============================================

class AgentDecision(BaseModel):
    """模型给出的操作决策"""

    # 决策核心
    suggested_operation: Literal["CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW"] = Field(
        description="建议的操作类型"
    )
    operation_reasoning: str = Field(description="决策理由，说明判断依据")
    matched_record_id: Optional[str] = Field(None, description="匹配到的旧账记录ID")
    confidence: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        description="模型对决策的置信度"
    )

    # 业务数据
    charge_details: ChargeDetails
    document_info: DocumentInfo
    transaction_party: TransactionParty
    financial_attributes: FinancialAttributes

    # 证据
    evidence: List[Evidence] = Field(default_factory=list)
    revision_requested: bool = Field(False, description="是否提取到明确修订声明；不是程序修改授权")
    revision_evidence: List[Evidence] = Field(default_factory=list)

    # 可选的字段变更说明（UPDATE时）
    field_changes: Optional[Dict[str, Any]] = Field(
        None,
        description="UPDATE操作时，说明哪些字段需要修改"
    )


class ExcludedItem(BaseModel):
    """被排除的项目（如条件条款、汇总行等）"""
    item_type: Literal["conditional_charge", "summary_line", "historical_reference", "other"]
    description: str
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    reasoning: str = Field(description="为什么排除")
    evidence: List[Evidence] = Field(default_factory=list)


class AgentDecisionBatch(BaseModel):
    """一批费用的决策结果"""
    decisions: List[AgentDecision] = Field(default_factory=list)
    excluded_items: List[ExcludedItem] = Field(default_factory=list)
    document_summary: Optional[Any] = Field(None, description="文档级汇总信息（字符串或字典）")
    processing_metadata: Dict[str, Any] = Field(default_factory=dict)
    processing_timestamp: datetime = Field(default_factory=datetime.now)
    extraction_errors: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================
# 程序验证相关
# ============================================

class MatchResult(BaseModel):
    """程序匹配结果"""
    matched: bool
    record_id: Optional[str] = None
    match_method: Optional[str] = Field(
        None,
        description="匹配方法：document_number, bill_of_lading等"
    )
    match_confidence: Optional[str] = Field(None, description="匹配置信度")
    candidates: List[str] = Field(default_factory=list, description="如果有多个候选")
    match_details: Optional[str] = None


class ValidationResult(BaseModel):
    """程序验证结果"""
    is_valid: bool = Field(description="是否通过验证")
    program_operation: Literal["CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW"] = Field(
        description="程序独立判断的操作类型"
    )
    program_matched_record_id: Optional[str] = Field(None, description="程序匹配到的记录ID")

    # 验证问题
    validation_issues: List[str] = Field(default_factory=list, description="验证发现的问题")
    match_conflicts: List[str] = Field(default_factory=list, description="匹配冲突")

    # 程序的匹配结果
    match_result: Optional[MatchResult] = None


# ============================================
# 最终操作
# ============================================

class AuditTrail(BaseModel):
    """审计追踪"""
    operation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)

    # 决策过程
    agent_operation: str
    agent_reasoning: str
    agent_confidence: str

    program_operation: str
    validation_issues: List[str]

    final_operation: str
    conflict_resolution: Optional[str] = None

    # 变更详情（UPDATE时）
    field_changes: Optional[Dict[str, Any]] = None
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None


class FinalOperation(BaseModel):
    """最终确定的操作"""
    operation: Literal["CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW"]
    record_id: Optional[str] = Field(None, description="记录ID，UPDATE时必需")

    # 决策过程
    agent_decision: AgentDecision
    validation_result: ValidationResult
    conflict_resolution: Optional[str] = Field(None, description="如何解决模型和程序的冲突")

    # 审计信息
    audit_trail: AuditTrail

    # 最终的业务数据（合并后）
    final_charge_details: ChargeDetails
    final_document_info: DocumentInfo
    final_transaction_party: TransactionParty
    final_financial_attributes: FinancialAttributes
    final_evidence: List[Evidence]


# ============================================
# 账本相关
# ============================================

class LedgerRecord(BaseModel):
    """账本记录"""
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # 业务数据
    charge_details: ChargeDetails
    document_info: DocumentInfo
    transaction_party: TransactionParty
    financial_attributes: FinancialAttributes
    evidence: List[Evidence] = Field(default_factory=list)
    doc_id: Optional[str] = None
    record_kind: str = Field("charge_line", description="charge_line或保留的legacy_summary")

    # 审计历史
    audit_history: List[AuditTrail] = Field(default_factory=list)

    # 创建和更新时间
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # 版本号
    version: int = Field(default=1)

    # 扩展字段（保留未知字段）
    extra_fields: Dict[str, Any] = Field(default_factory=dict)


class Ledger(BaseModel):
    """完整账本"""
    ledger_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: int = Field(default=1)
    accounting_entity: str = Field(description="记账主体")

    records: List[LedgerRecord] = Field(default_factory=list)

    # 已应用的操作ID集合（用于幂等性）
    applied_operations: List[str] = Field(default_factory=list)

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def has_record(self, record_id: str) -> bool:
        """检查记录是否存在"""
        return any(r.record_id == record_id for r in self.records)

    def get_record(self, record_id: str) -> Optional[LedgerRecord]:
        """获取指定记录"""
        for record in self.records:
            if record.record_id == record_id:
                return record
        return None

    def is_operation_applied(self, operation_id: str) -> bool:
        """检查操作是否已应用"""
        return operation_id in self.applied_operations


# ============================================
# 输出结果
# ============================================

class ProcessingResult(BaseModel):
    """单个费用的处理结果"""
    operation: Literal["CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW"]
    record_id: Optional[str] = None

    # 决策过程展示
    model_suggestion: str
    model_confidence: str
    model_reasoning: str

    program_validation: str
    validation_issues: List[str]

    conflict_resolution: Optional[str] = None

    # 业务数据
    charge_details: Dict[str, Any]
    document_info: Dict[str, Any]
    transaction_party: Dict[str, Any]
    financial_attributes: Dict[str, Any]

    # 证据
    evidence: List[Dict[str, Any]]

    # 审计
    audit_trail: Dict[str, Any]


class RunReport(BaseModel):
    """运行报告"""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)

    # 文件处理状态
    files_processed: int = 0
    files_succeeded: int = 0
    files_failed: int = 0

    # 操作统计
    operations_summary: Dict[str, int] = Field(
        default_factory=lambda: {
            "CREATE": 0,
            "UPDATE": 0,
            "NO_CHANGE": 0,
            "PENDING_REVIEW": 0
        }
    )

    # 排除项
    excluded_items: List[ExcludedItem] = Field(default_factory=list)

    # 文件级错误
    file_errors: List[Dict[str, str]] = Field(default_factory=list)

    # API调用状态
    model_calls: int = 0
    ocr_calls: int = 0
    api_errors: int = 0

    # 配置状态
    using_mock_data: bool = False
    model_configured: bool = False
    ocr_configured: bool = False
