# 🔍 程序验证机制详解

## 📊 双重验证架构

### 旧版本设计（原始架构）

```
┌─────────────────────────────────────────────────────────────┐
│                      输入：新单据                              │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
┌──────────────┐          ┌──────────────┐
│   LLM Agent  │          │  Validator   │
│  (模型决策)   │          │  (程序验证)   │
└──────┬───────┘          └──────┬───────┘
       │                         │
       │ 给出决策                 │ 独立验证
       │ ├─ CREATE              │ ├─ CREATE
       │ ├─ UPDATE              │ ├─ UPDATE
       │ ├─ NO_CHANGE           │ ├─ NO_CHANGE
       │ └─ 置信度: HIGH         │ └─ 匹配方法
       │                         │
       └────────┬────────────────┘
                │
                ▼
        ┌───────────────┐
        │  冲突解决器     │
        │ 对比两个决策    │
        └───────┬───────┘
                │
                ▼
        ┌───────────────┐
        │  最终决策      │
        │ CREATE/UPDATE │
        └───────────────┘
```

---

## 🎯 程序验证的核心逻辑

### 验证步骤

#### 步骤1：基础字段验证

```python
def _validate_basic_fields(decision):
    """验证必需字段是否完整"""
    issues = []
    
    # 检查1：费用名称
    if not decision.charge_details.original_name:
        issues.append("费用名称不能为空")
    
    # 检查2：金额
    if decision.charge_details.amount is None:
        issues.append("金额不能为空")
    
    # 检查3：币种
    if not decision.charge_details.currency:
        issues.append("币种不能为空")
    
    # 检查4：币种格式（ISO 4217）
    if not is_valid_currency(decision.charge_details.currency):
        issues.append("币种格式不正确，应为3位大写字母")
    
    return issues
```

**验证内容**：
- ✅ 费用名称不为空
- ✅ 金额不为空且合理
- ✅ 币种符合 ISO 4217 标准（如 USD、CNY、EUR）

---

#### 步骤2：独立旧账匹配

程序**完全独立**于 LLM，自己进行旧账匹配：

```python
def _independent_match(decision, ledger):
    """程序独立匹配旧账，不依赖 LLM 的判断"""
    
    # 匹配层级（从强到弱）
    
    # 层级1：单据号 + 标准费用名称 ⭐⭐⭐⭐⭐
    if document_number and standardized_name:
        匹配 = 查找(单据号相同 AND 费用名称相同)
        if 找到唯一记录:
            return MatchResult(
                matched=True,
                record_id="REC-123",
                match_confidence="HIGH"
            )
    
    # 层级2：提单号 + 标准费用名称 + 币种 ⭐⭐⭐⭐
    if bill_of_lading and standardized_name and currency:
        匹配 = 查找(提单号相同 AND 费用名称相同 AND 币种相同)
        if 找到唯一记录:
            return MatchResult(
                matched=True,
                record_id="REC-456",
                match_confidence="MEDIUM"
            )
    
    # 层级3：订舱号 + 标准费用名称 + 币种 ⭐⭐⭐
    # 层级4：箱号 + 原始名称 + 金额 + 币种 ⭐⭐
    
    # 没有找到匹配
    return MatchResult(matched=False)
```

**匹配优先级**：
1. **最强**：单据号 + 费用名称
2. **次强**：提单号 + 费用名称 + 币种
3. **中等**：订舱号 + 费用名称 + 币种
4. **较弱**：箱号 + 原始名称 + 金额 + 币种

---

#### 步骤3：确定程序操作

```python
def _determine_program_operation(decision, match_result, issues):
    """程序给出自己的操作建议"""
    
    # 规则1：有验证问题 → PENDING_REVIEW
    if issues or match_conflicts:
        return "PENDING_REVIEW"
    
    # 规则2：没有找到匹配 → CREATE
    if not match_result.matched:
        if match_result.candidates:  # 有多个候选
            return "PENDING_REVIEW"  # 无法唯一确定
        else:
            return "CREATE"  # 确实是新记录
    
    # 规则3：找到唯一匹配
    if match_result.matched:
        if LLM建议UPDATE:
            return "UPDATE"  # 确认更新
        else:
            return "NO_CHANGE"  # 数据相同
```

---

## 🔄 决策对比与冲突解决

### 对比矩阵

| LLM 决策 | 程序验证 | 最终决策 | 说明 |
|---------|---------|---------|------|
| CREATE | CREATE | ✅ CREATE | 双方一致 |
| UPDATE | UPDATE | ✅ UPDATE | 双方一致 |
| NO_CHANGE | NO_CHANGE | ✅ NO_CHANGE | 双方一致 |
| CREATE | UPDATE | ⚠️ PENDING_REVIEW | 冲突：需人工审核 |
| UPDATE | CREATE | ⚠️ PENDING_REVIEW | 冲突：需人工审核 |
| UPDATE | NO_CHANGE | ⚠️ PENDING_REVIEW | 冲突：需人工审核 |

### 冲突解决策略

```python
if model_decision != program_decision:
    # 策略1：程序优先（保守策略）
    if program_confidence == "HIGH":
        final_decision = program_decision
        conflict_resolution = "程序高置信度匹配，采用程序决策"
    
    # 策略2：人工审核（安全策略）
    else:
        final_decision = "PENDING_REVIEW"
        conflict_resolution = f"模型建议{model_decision}，程序建议{program_decision}，需人工确认"
```

---

## 📊 验证结果示例

### 示例1：完美匹配

```json
{
  "model_decision": {
    "suggested_operation": "UPDATE",
    "confidence": "HIGH",
    "matched_record_id": "REC-123",
    "operation_reasoning": "单据号相同，金额从50改为40"
  },
  "validation_result": {
    "is_valid": true,
    "program_operation": "UPDATE",
    "program_matched_record_id": "REC-123",
    "match_confidence": "HIGH",
    "validation_issues": []
  },
  "final_operation": {
    "operation": "UPDATE",
    "conflict_resolution": null
  }
}
```

### 示例2：存在冲突

```json
{
  "model_decision": {
    "suggested_operation": "CREATE",
    "confidence": "MEDIUM",
    "matched_record_id": null
  },
  "validation_result": {
    "is_valid": true,
    "program_operation": "UPDATE",
    "program_matched_record_id": "REC-456",
    "match_confidence": "HIGH",
    "validation_issues": []
  },
  "final_operation": {
    "operation": "PENDING_REVIEW",
    "conflict_resolution": "模型认为是新记录，但程序通过提单号匹配到旧记录REC-456，建议人工审核"
  }
}
```

---

## 🆕 当前系统状态（智能 CRUD 优化后）

### 新架构

```
┌─────────────────────────────────────────────────────────────┐
│                      输入：新单据                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
             ┌──────────────┐
             │   LLM Agent  │
             │ 只提取信息    │
             │ 不判断操作    │
             └──────┬───────┘
                    │
                    │ 费用信息：
                    │ - 操作费 40 USD
                    │ - 单据号 DN-2024-001
                    │
                    ▼
        ┌───────────────────────┐
        │  SmartCRUDExecutor    │
        │  程序直接决策并执行     │
        └───────────┬───────────┘
                    │
                    ├─ 1. 检索数据库
                    ├─ 2. 匹配旧记录
                    ├─ 3. 比较数据变化
                    ├─ 4. 判断 CREATE/UPDATE
                    └─ 5. 直接执行
```

**变化**：
- ❌ 不再有"双重验证"
- ❌ 不再有"冲突解决"
- ✅ 程序完全负责判断和执行
- ✅ LLM 只负责信息提取

---

## 🔧 为什么要改成新架构？

### 旧架构的问题

1. **Token 浪费**
   - 需要传递完整旧账给 LLM
   - 旧账越多，成本越高

2. **LLM 判断不可靠**
   - 可能产生幻觉
   - 匹配逻辑不够精确

3. **冗余验证**
   - 程序验证已经很准确
   - LLM 验证反而增加复杂度

### 新架构的优势

1. **节省 99% Token** ⚡
   - 不需要传递旧账
   - 只传递当前文档

2. **更高准确性** 🎯
   - 程序匹配确定性强
   - SQL 查询精确

3. **更快速度** 🚀
   - 数据库查询毫秒级
   - 减少 LLM 调用时间

---

## 📝 总结

### 旧版本（Validator）

**程序验证做什么**：
1. ✅ 验证基础字段完整性
2. ✅ 独立进行旧账匹配
3. ✅ 给出程序的操作建议
4. ✅ 与 LLM 决策对比
5. ✅ 解决冲突

**验证依据**：
- 单据号、提单号、订舱号、箱号
- 费用名称（标准化后）
- 金额、币种
- 多层级匹配规则

---

### 新版本（SmartCRUDExecutor）

**程序做什么**：
1. ✅ 接收 LLM 提取的费用信息
2. ✅ 检索数据库查找匹配记录
3. ✅ 直接判断 CREATE/UPDATE/NO_CHANGE
4. ✅ 执行操作

**判断依据**：
- SQL 精确查询
- 数据变化检测
- 确定性的程序逻辑

---

**核心理念：程序擅长的事情（精确匹配、数据对比）就让程序做，LLM 擅长的事情（信息提取、语义理解）就让 LLM 做！** 🎯
