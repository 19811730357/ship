# 🔍 系统如何识别同一单号

## 完整识别流程

### 步骤1：从数据库加载历史记录

**代码位置**：`src/billing_agent/workflow_db.py:80`

```python
# 从数据库加载所有历史记录
ledger = self.db.load_ledger(self.accounting_entity)

# 示例输出：
# [OK] Loaded ledger from database: 5 records
#   Recent records:
#     - 操作费: 50.0 USD (Doc: DN-2024-001)
#     - 文件费: 30.0 USD (Doc: DN-2024-001)
#     - 码头费: 120.0 USD (Doc: DN-2024-002)
```

### 步骤2：格式化旧账摘要

**代码位置**：`src/billing_agent/agent.py:121-147`

```python
def format_ledger_summary(ledger: Ledger) -> str:
    """将历史记录格式化为文本，供 LLM 阅读"""
    summary_parts = []
    for idx, record in enumerate(ledger.records, 1):
        summary_parts.append(
            f"记录 #{idx}:\n"
            f"  - ID: {record.record_id}\n"
            f"  - 费用名称: {record.charge_details.original_name}\n"
            f"  - 金额: {record.charge_details.amount} {record.charge_details.currency}\n"
            f"  - 单据号: {record.document_info.document_number or 'N/A'}\n"
            f"  - 提单号: {record.document_info.bill_of_lading or 'N/A'}\n"
        )
    return "\n".join(summary_parts)
```

**格式化后的旧账摘要示例**：
```
记录 #1:
  - ID: REC-abc123
  - 费用名称: HANDLING CHARGE
  - 标准名称: 操作费
  - 金额: 50.0 USD
  - 付款方式: Prepaid
  - 单据号: DN-2024-001
  - 提单号: BL-2024-001

记录 #2:
  - ID: REC-def456
  - 费用名称: DOCUMENTATION FEE
  - 标准名称: 文件费
  - 金额: 30.0 USD
  - 付款方式: Prepaid
  - 单据号: DN-2024-001
  - 提单号: BL-2024-001
```

### 步骤3：传递给 LLM Agent

**代码位置**：`src/billing_agent/agent.py:320-327`

```python
# 传递给模型
response = self.chain.invoke({
    "accounting_entity": self.accounting_entity,
    "material_content": material_content,      # 新上传的文档内容
    "ledger_summary": ledger_summary            # 历史记录摘要
})
```

### 步骤4：LLM 分析和匹配

**Prompt 指示**（`src/billing_agent/agent.py:32-42`）：

```
**操作类型判断**：
- CREATE: 这是新的实际费用，旧账中没有对应记录
- UPDATE: 原文明确要修改某个费用，且能唯一匹配到旧账记录
- NO_CHANGE: 这个费用已存在于旧账，且没有变化

**重要规则**：
1. 条件收费条款（"如果...则收取"、"若超期..."）不是实际费用，应该排除到excluded_items
2. 同名费用有多条旧账时，必须有额外标识（如原金额、单据号）才能唯一匹配
3. UPDATE操作必须明确指出matched_record_id
4. 给出清晰的operation_reasoning，说明你的判断依据
```

### 步骤5：LLM 输出决策

**模型输出示例**：

```json
{
  "decisions": [
    {
      "suggested_operation": "UPDATE",
      "matched_record_id": "REC-abc123",
      "operation_reasoning": "材料中明确提到'请将操作费从50美元改为40美元'，且能通过单据号DN-2024-001和费用名称'操作费'唯一匹配到旧账记录#1",
      "confidence": "HIGH",
      "charge_details": {
        "original_name": "HANDLING CHARGE",
        "standardized_name": "操作费",
        "amount": 40.0,
        "currency": "USD"
      },
      "document_info": {
        "document_number": "DN-2024-001",
        "bill_of_lading": "BL-2024-001"
      }
    }
  ]
}
```

---

## 🎯 匹配依据

LLM 根据以下信息匹配同一单号：

### 主要匹配字段（优先级从高到低）

1. **单据号（document_number）** - 最强匹配
   - 例如：`DN-2024-001`
   - 如果单据号相同，通常就是同一单据

2. **提单号（bill_of_lading）** - 次强匹配
   - 例如：`BL-2024-001`
   - 一个提单可能包含多个费用

3. **费用名称（charge_name）** - 辅助匹配
   - 例如：`HANDLING CHARGE`、`操作费`
   - 需要配合其他字段

4. **金额（amount）** - 辅助验证
   - 例如：修改前是 50 USD，修改后是 40 USD
   - 用于确认是否匹配正确

### 匹配逻辑示例

**场景1：明确的单据号**
```
新材料：DN-2024-001 的操作费改为 40 USD
旧账：DN-2024-001 的操作费 50 USD
结果：✅ 匹配成功 → UPDATE
```

**场景2：提单号 + 费用名称**
```
新材料：BL-2024-001 的文件费改为 25 USD
旧账：BL-2024-001 的文件费 30 USD
结果：✅ 匹配成功 → UPDATE
```

**场景3：模糊匹配（多条记录）**
```
新材料：操作费改为 40 USD（没有单据号）
旧账：
  - 记录1：DN-2024-001 的操作费 50 USD
  - 记录2：DN-2024-002 的操作费 60 USD
结果：❌ 无法唯一匹配 → 标记为 PENDING_REVIEW
```

---

## 🔧 程序验证层

在 LLM 判断后，还有程序验证层进一步确认：

**代码位置**：`src/billing_agent/validator.py`

```python
class Validator:
    def validate_decision(self, decision: AgentDecision, ledger: Ledger) -> ValidationResult:
        """验证模型的决策是否合理"""
        
        if decision.suggested_operation == "UPDATE":
            # 检查是否指定了 matched_record_id
            if not decision.matched_record_id:
                return ValidationResult(
                    is_valid=False,
                    issues=["UPDATE操作必须指定matched_record_id"]
                )
            
            # 检查记录是否真的存在
            old_record = ledger.get_record(decision.matched_record_id)
            if not old_record:
                return ValidationResult(
                    is_valid=False,
                    issues=[f"matched_record_id {decision.matched_record_id} 不存在"]
                )
```

---

## 📊 完整流程图

```
1. 用户上传文档
        ↓
2. 从 MySQL 加载历史记录
   SELECT * FROM ledger_records WHERE accounting_entity = 'Demo Company'
        ↓
3. 格式化为文本摘要
   记录 #1: ID=REC-abc123, 单据号=DN-2024-001, 操作费=50 USD
        ↓
4. 传递给 LLM
   Prompt: "分析新材料和旧账，判断是 CREATE/UPDATE/NO_CHANGE"
   Context: 
     - 新材料：请将 DN-2024-001 的操作费改为 40 USD
     - 旧账：DN-2024-001 的操作费 50 USD
        ↓
5. LLM 分析匹配
   - 发现单据号相同：DN-2024-001 ✅
   - 发现费用名称相同：操作费 ✅
   - 金额变化：50 → 40 ✅
   - 判断：UPDATE
   - 输出：matched_record_id = "REC-abc123"
        ↓
6. 程序验证
   - 检查 REC-abc123 是否存在 ✅
   - 检查金额是否真的变化 ✅
   - 验证通过
        ↓
7. 冲突解决（如果模型和程序不一致）
        ↓
8. 执行操作
   UPDATE ledger_records 
   SET amount = 40.0, updated_at = NOW()
   WHERE record_id = 'REC-abc123'
        ↓
9. 保存处理历史
   INSERT INTO processing_history (...)
```

---

## 💡 关键点总结

### ✅ 识别机制
1. **数据库记忆** - 从 MySQL 加载所有历史记录
2. **上下文传递** - 将历史记录格式化为文本传给 LLM
3. **智能匹配** - LLM 基于单据号、提单号、费用名称等匹配
4. **程序验证** - 双重检查确保匹配正确
5. **冲突解决** - 如果不一致，有明确的解决策略

### ✅ 匹配优先级
1. **单据号** (document_number) - 最可靠
2. **提单号** (bill_of_lading) - 次可靠
3. **费用名称 + 金额** - 辅助匹配

### ✅ 安全机制
- 如果无法唯一匹配 → 标记为 `PENDING_REVIEW`
- 如果匹配不确定 → 置信度降低为 `LOW`
- 如果程序验证失败 → 拒绝操作

---

## 🧪 测试验证

### 测试1：单据号匹配
```bash
# 第一次
上传文档：DN-2024-001, 操作费 50 USD
结果：CREATE

# 第二次（重启后）
上传文档：DN-2024-001, 操作费改为 40 USD
结果：UPDATE (matched_record_id 正确)
```

### 测试2：查看数据库
```sql
-- 查看记录
SELECT 
    record_id,
    charge_name,
    amount,
    document_number,
    updated_at
FROM ledger_records
WHERE document_number = 'DN-2024-001';

-- 查看处理历史
SELECT 
    operation,
    model_suggestion,
    matched_record_id,
    model_reasoning
FROM processing_history
ORDER BY processed_at DESC
LIMIT 5;
```

---

**总结：系统通过"数据库记忆 + LLM 智能匹配 + 程序验证"三层机制，准确识别同一单号！**
