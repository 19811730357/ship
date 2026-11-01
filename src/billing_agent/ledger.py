"""
账本管理和冲突解决
处理旧账匹配、冲突解决和快照生成
"""

from typing import Optional, Dict, Any
from datetime import datetime
from copy import deepcopy

from .models import (
    AgentDecision,
    ValidationResult,
    FinalOperation,
    AuditTrail,
    Ledger,
    LedgerRecord,
    ChargeDetails,
    DocumentInfo,
    TransactionParty,
    FinancialAttributes,
    Evidence
)


def resolve_operation(
    agent_decision: AgentDecision,
    validation_result: ValidationResult,
    ledger: Ledger
) -> FinalOperation:
    """
    解决模型和程序的冲突，确定最终操作

    策略：
    1. 验证失败直接转PENDING_REVIEW
    2. 模型和程序一致时采纳
    3. 模型更乐观（UPDATE vs PENDING_REVIEW）时，根据置信度决定
    4. 其他不一致情况转PENDING_REVIEW

    Args:
        agent_decision: 模型的决策
        validation_result: 程序的验证结果
        ledger: 当前账本

    Returns:
        FinalOperation: 最终操作
    """
    model_op = agent_decision.suggested_operation
    program_op = validation_result.program_operation

    # 策略1: 验证失败直接转PENDING_REVIEW
    if not validation_result.is_valid:
        conflict_resolution = "程序验证发现问题，需人工复核"
        final_op = "PENDING_REVIEW"
        record_id = None

    # 策略2: 一致时采纳
    elif model_op == program_op:
        conflict_resolution = "模型和程序判断一致"
        final_op = model_op
        record_id = agent_decision.matched_record_id or validation_result.program_matched_record_id

    # 策略3: 模型更乐观（UPDATE vs PENDING_REVIEW）
    elif model_op == "UPDATE" and program_op == "PENDING_REVIEW":
        if agent_decision.confidence == "HIGH":
            conflict_resolution = "程序发现歧义，但模型高置信度，采纳UPDATE"
            final_op = "UPDATE"
            record_id = agent_decision.matched_record_id
        else:
            conflict_resolution = "存在歧义且模型置信度不高，谨慎处理"
            final_op = "PENDING_REVIEW"
            record_id = None

    # 策略4: 模型说CREATE但程序说有匹配
    elif model_op == "CREATE" and program_op in ["UPDATE", "NO_CHANGE"]:
        conflict_resolution = f"模型建议CREATE，但程序找到旧账匹配（{program_op}），存在冲突"
        final_op = "PENDING_REVIEW"
        record_id = validation_result.program_matched_record_id

    # 策略5: 其他不一致情况
    else:
        conflict_resolution = f"模型建议{model_op}，程序判断{program_op}，存在冲突"
        final_op = "PENDING_REVIEW"
        record_id = None

    # 构建审计追踪
    audit_trail = AuditTrail(
        agent_operation=model_op,
        agent_reasoning=agent_decision.operation_reasoning,
        agent_confidence=agent_decision.confidence,
        program_operation=program_op,
        validation_issues=validation_result.validation_issues + validation_result.match_conflicts,
        final_operation=final_op,
        conflict_resolution=conflict_resolution
    )

    # 如果是UPDATE，记录字段变更
    if final_op == "UPDATE" and record_id:
        old_record = ledger.get_record(record_id)
        if old_record:
            audit_trail.old_values = _extract_values(old_record)
            audit_trail.new_values = _extract_values_from_decision(agent_decision)
            audit_trail.field_changes = agent_decision.field_changes

    # 构建最终操作
    return FinalOperation(
        operation=final_op,
        record_id=record_id,
        agent_decision=agent_decision,
        validation_result=validation_result,
        conflict_resolution=conflict_resolution,
        audit_trail=audit_trail,
        final_charge_details=agent_decision.charge_details,
        final_document_info=agent_decision.document_info,
        final_transaction_party=agent_decision.transaction_party,
        final_financial_attributes=agent_decision.financial_attributes,
        final_evidence=agent_decision.evidence
    )


def apply_operation(
    final_op: FinalOperation,
    ledger: Ledger
) -> Ledger:
    """
    应用最终操作到账本

    Args:
        final_op: 最终操作
        ledger: 当前账本

    Returns:
        更新后的账本（新对象）
    """
    # 复制账本
    new_ledger = deepcopy(ledger)

    # 检查操作是否已应用
    if new_ledger.is_operation_applied(final_op.audit_trail.operation_id):
        # 已应用，跳过
        return new_ledger

    # 根据操作类型处理
    if final_op.operation == "CREATE":
        # 创建新记录
        new_record = LedgerRecord(
            charge_details=final_op.final_charge_details,
            document_info=final_op.final_document_info,
            transaction_party=final_op.final_transaction_party,
            financial_attributes=final_op.final_financial_attributes,
            audit_history=[final_op.audit_trail]
        )
        new_ledger.records.append(new_record)
        new_ledger.applied_operations.append(final_op.audit_trail.operation_id)
        new_ledger.version += 1

    elif final_op.operation == "UPDATE":
        # 更新现有记录
        if final_op.record_id:
            for i, record in enumerate(new_ledger.records):
                if record.record_id == final_op.record_id:
                    # 更新字段（只更新明确变更的字段）
                    updated_record = _merge_update(
                        record,
                        final_op.final_charge_details,
                        final_op.final_document_info,
                        final_op.final_transaction_party,
                        final_op.final_financial_attributes,
                        final_op.audit_trail
                    )
                    new_ledger.records[i] = updated_record
                    break

            new_ledger.applied_operations.append(final_op.audit_trail.operation_id)
            new_ledger.version += 1

    elif final_op.operation == "NO_CHANGE":
        # 记录操作但不修改数据
        new_ledger.applied_operations.append(final_op.audit_trail.operation_id)

    # PENDING_REVIEW不应用到快照

    # 更新时间戳
    new_ledger.updated_at = datetime.now()

    return new_ledger


def _merge_update(
    old_record: LedgerRecord,
    new_charge: ChargeDetails,
    new_doc: DocumentInfo,
    new_party: TransactionParty,
    new_financial: FinancialAttributes,
    audit: AuditTrail
) -> LedgerRecord:
    """
    合并更新：只更新明确变更的字段，其他字段保留旧值

    Args:
        old_record: 旧记录
        new_charge: 新费用详情
        new_doc: 新单据信息
        new_party: 新交易方
        new_financial: 新财务属性
        audit: 审计追踪

    Returns:
        更新后的记录
    """
    # 复制旧记录
    updated = deepcopy(old_record)

    # 如果有明确的字段变更列表，只更新这些字段
    if audit.field_changes:
        for field_path, new_value in audit.field_changes.items():
            _set_nested_field(updated, field_path, new_value)
    else:
        # 没有明确列表，更新所有非空字段（保守策略）
        # 实际应该由模型明确指定哪些字段需要更新
        if new_charge.amount != old_record.charge_details.amount:
            updated.charge_details.amount = new_charge.amount
        if new_charge.payment_method and new_charge.payment_method != old_record.charge_details.payment_method:
            updated.charge_details.payment_method = new_charge.payment_method

    # 追加审计历史
    updated.audit_history.append(audit)
    updated.updated_at = datetime.now()
    updated.version += 1

    return updated


def _set_nested_field(obj: Any, field_path: str, value: Any):
    """设置嵌套字段值"""
    parts = field_path.split('.')
    current = obj
    for part in parts[:-1]:
        current = getattr(current, part)
    setattr(current, parts[-1], value)


def _extract_values(record: LedgerRecord) -> Dict[str, Any]:
    """从记录中提取值用于审计"""
    return {
        "amount": str(record.charge_details.amount),
        "currency": record.charge_details.currency,
        "payment_method": record.charge_details.payment_method,
        "original_name": record.charge_details.original_name,
        "posting_type": record.financial_attributes.posting_type
    }


def _extract_values_from_decision(decision: AgentDecision) -> Dict[str, Any]:
    """从决策中提取值用于审计"""
    return {
        "amount": str(decision.charge_details.amount),
        "currency": decision.charge_details.currency,
        "payment_method": decision.charge_details.payment_method,
        "original_name": decision.charge_details.original_name,
        "posting_type": decision.financial_attributes.posting_type
    }


def load_ledger_from_dict(data: Dict[str, Any], accounting_entity: str) -> Ledger:
    """
    从字典加载账本

    支持两种格式：
    1. 完整快照（包含ledger_id, version等）
    2. 简单的记录数组

    Args:
        data: 字典数据
        accounting_entity: 当前记账主体

    Returns:
        Ledger对象
    """
    # 如果是完整快照格式
    if "ledger_id" in data and "records" in data:
        # 验证记账主体
        if data.get("accounting_entity") != accounting_entity:
            raise ValueError(
                f"记账主体不一致: 快照={data.get('accounting_entity')}, "
                f"当前={accounting_entity}"
            )
        return Ledger(**data)

    # 如果是简单的记录数组
    elif isinstance(data, list):
        # 检查所有记录的记账主体
        for i, record_data in enumerate(data):
            if "financial_attributes" in record_data:
                entity = record_data["financial_attributes"].get("accounting_entity")
                if entity and entity != accounting_entity:
                    raise ValueError(
                        f"记录#{i}的记账主体({entity})与当前主体({accounting_entity})不一致"
                    )

        # 转换为LedgerRecord列表
        records = [LedgerRecord(**r) for r in data]
        return Ledger(
            accounting_entity=accounting_entity,
            records=records
        )

    else:
        raise ValueError("不支持的账本格式")


def generate_processing_results(final_operations: list) -> list:
    """
    生成处理结果JSON

    Args:
        final_operations: FinalOperation列表

    Returns:
        处理结果列表（字典格式）
    """
    results = []

    for final_op in final_operations:
        result = {
            "operation": final_op.operation,
            "record_id": final_op.record_id,

            # 决策过程
            "model_suggestion": final_op.agent_decision.suggested_operation,
            "model_confidence": final_op.agent_decision.confidence,
            "model_reasoning": final_op.agent_decision.operation_reasoning,

            "program_validation": final_op.validation_result.program_operation,
            "validation_issues": final_op.validation_result.validation_issues,

            "conflict_resolution": final_op.conflict_resolution,

            # 业务数据
            "charge_details": final_op.final_charge_details.model_dump(),
            "document_info": final_op.final_document_info.model_dump(),
            "transaction_party": final_op.final_transaction_party.model_dump(),
            "financial_attributes": final_op.final_financial_attributes.model_dump(),

            # 证据
            "evidence": [e.model_dump() for e in final_op.final_evidence],

            # 审计
            "audit_trail": final_op.audit_trail.model_dump()
        }

        results.append(result)

    return results
