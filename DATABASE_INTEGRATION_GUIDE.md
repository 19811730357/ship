# 🎉 数据库集成完成 - 使用指南

## ✅ 已完成的集成

### 核心改进

1. **数据库持久化** - 所有记录保存到数据库，重启后数据不丢失
2. **智能增量处理** - 自动识别同一单据的 UPDATE 操作
3. **历史追溯** - 完整的处理历史和审计日志
4. **文档去重** - 自动检测已处理的文档，避免重复处理

### 新增文件

- `src/billing_agent/database.py` - 数据库管理模块
- `src/billing_agent/workflow_db.py` - 数据库集成工作流
- `demo_database.py` - 数据库演示脚本

---

## 🚀 使用方式

### 方式1：Streamlit 应用（推荐）

```bash
# 启动应用
streamlit run app.py
```

#### 界面操作步骤

1. **侧边栏配置**
   - ✅ 勾选"启用数据库持久化"
   - 选择数据库类型（默认 SQLite）
   - 设置数据库文件名（默认 billing.db）

2. **上传文件**
   - 选择"真实文件处理"模式
   - 上传文档（支持 PDF、Word、Excel、TXT 等）
   - 可选：上传旧账 JSON 或勾选"使用空账本"

3. **开始处理**
   - 点击"🚀 开始处理"
   - 系统会自动：
     - 从数据库加载历史记录
     - 检查文档是否已处理
     - Agent 决策（识别 CREATE/UPDATE）
     - 保存结果到数据库

4. **查看结果**
   - 📊 处理摘要
   - 📋 处理结果详情
   - 💾 **数据库统计**（总记录数、唯一单据数、唯一提单数）
   - 📥 下载 JSON 文件

---

## 🎯 核心场景演示

### 场景1：第一次处理单据

```
操作: 上传 bill_1.pdf
内容: BL-2024-001, 操作费 50 USD

结果:
✅ CREATE 操作费 50 USD
💾 已保存到数据库: 1 条记录
```

### 场景2：重启应用后修改同一单据

```
操作: 重启 streamlit，再次上传 bill_2.pdf
内容: BL-2024-001, 操作费改为 30 USD

流程:
1. 从数据库加载旧账: 1 条记录
2. Agent 分析材料
3. 识别为 UPDATE（而不是 CREATE！）
4. 更新数据库记录

结果:
✅ UPDATE 操作费 30 USD
💾 数据库记录已更新
📊 总记录数: 1（更新现有记录，不增加）
```

### 场景3：重复处理同一文档

```
操作: 上传完全相同的文件

流程:
1. 计算文件 SHA256 哈希
2. 检查 document_processing 表
3. 发现已处理过

结果:
⚠️ 文件已处理过，跳过
📅 上次处理时间: 2024-10-31 15:30:00
```

---

## 📊 数据库表说明

### 1. ledger_records - 账本记录表

**存储内容**: 所有费用记录

**关键字段**:
- `record_id` - 记录唯一ID
- `document_number` - 单据号（用于匹配）
- `bill_of_lading` - 提单号（用于匹配）
- `charge_name` - 费用名称
- `amount` - 金额
- `currency` - 币种
- `record_data` - 完整 JSON 数据

**查询示例**:
```sql
-- 查看所有记录
SELECT * FROM ledger_records ORDER BY created_at DESC;

-- 按单据号查询
SELECT * FROM ledger_records WHERE document_number = 'DN-2024-001';

-- 按提单号查询
SELECT * FROM ledger_records WHERE bill_of_lading = 'BL-2024-001';

-- 统计
SELECT COUNT(*) as total FROM ledger_records;
SELECT COUNT(DISTINCT document_number) FROM ledger_records;
```

### 2. processing_history - 处理历史表

**存储内容**: 每次决策的完整过程

**关键字段**:
- `session_id` - 会话ID（一次处理的所有决策）
- `operation` - 最终操作（CREATE/UPDATE/NO_CHANGE）
- `model_suggestion` - 模型建议
- `model_confidence` - 置信度
- `model_reasoning` - 决策理由
- `program_validation` - 程序验证结果
- `decision_data` - 完整决策 JSON

**用途**: 审计、回溯、分析模型表现

### 3. document_processing - 文档处理表

**存储内容**: 已处理的文档记录

**关键字段**:
- `document_hash` - 文件 SHA256 哈希（唯一）
- `file_name` - 文件名
- `processing_status` - 处理状态
- `results` - 处理结果 JSON

**用途**: 防止重复处理同一文档

---

## 🔧 数据库管理

### 查看数据（SQLite）

```bash
# 打开数据库
sqlite3 billing.db

# 查看所有表
.tables

# 查看记录
SELECT * FROM ledger_records;

# 查看统计
SELECT 
    COUNT(*) as total_records,
    COUNT(DISTINCT document_number) as unique_docs
FROM ledger_records;

# 退出
.exit
```

### 备份数据

```bash
# 备份 SQLite
cp billing.db billing_backup_$(date +%Y%m%d_%H%M%S).db

# 恢复
cp billing_backup_20241031_153000.db billing.db
```

### 清空数据

```bash
# 删除数据库文件
rm billing.db

# 或在数据库中清空表
sqlite3 billing.db "DELETE FROM ledger_records;"
sqlite3 billing.db "DELETE FROM processing_history;"
sqlite3 billing.db "DELETE FROM document_processing;"
```

---

## 📈 界面展示说明

### 侧边栏 - 数据库配置

```
💾 数据库配置
├─ ☑️ 启用数据库持久化
├─ 数据库类型: SQLite ▼
└─ 数据库文件: billing.db
   ✅ 数据库已启用
   📁 数据库位置: billing.db
```

### 处理结果 - 数据库统计

```
💾 数据库统计

📊 总记录数        📄 唯一单据数      🚢 唯一提单数
    15                 12                 10

✅ 所有数据已持久化到数据库，重启后依然可用
🔖 会话ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### 处理过程输出（控制台）

```
✓ 数据库已连接: sqlite - {'database': 'billing.db'}
✓ 从数据库加载旧账: 5 条记录
  最近的记录:
    - 操作费: 50.0 USD (单据: DN-2024-001)
    - 文件费: 30.0 USD (单据: DN-2024-001)
    - 码头费: 120.0 USD (单据: DN-2024-002)
✓ 会话ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890

===================================================================
📄 传递给模型的材料内容:
===================================================================
[材料内容...]
===================================================================

✓ 已保存到数据库: 操作费 - UPDATE
✓ 已保存到数据库: 文件费 - NO_CHANGE
```

---

## 🎓 进阶功能

### 1. 按单据号查询历史

在 Python 中：

```python
from billing_agent.database import DatabaseManager

db = DatabaseManager(db_type="sqlite", db_config={"database": "billing.db"})

# 查询单据的所有记录
records = db.query_records_by_document("DN-2024-001")
for record in records:
    print(f"{record.charge_details.original_name}: {record.charge_details.amount}")
```

### 2. 查看处理统计

```python
stats = db.get_processing_statistics("Demo Company")
print(f"总记录: {stats['total_records']}")
print(f"唯一单据: {stats['unique_documents']}")
print(f"唯一提单: {stats['unique_bls']}")
```

### 3. 导出数据

```python
# 导出账本为 JSON
ledger = db.load_ledger("Demo Company")
import json
with open("ledger_export.json", "w", encoding="utf-8") as f:
    json.dump([r.model_dump() for r in ledger.records], f, indent=2, default=str)
```

---

## ✅ 效果对比

| 场景 | 无数据库 | 有数据库 |
|------|---------|---------|
| 第一次处理 BL-2024-001 | CREATE ✅ | CREATE ✅ |
| 重启应用 | 数据丢失 ❌ | 数据保留 ✅ |
| 第二次处理同一单据 | CREATE ❌（错误！）| UPDATE ✅（正确！）|
| 重复上传相同文件 | 重复处理 ❌ | 自动跳过 ✅ |
| 历史追溯 | 不支持 ❌ | 完整审计 ✅ |
| 按单据查询 | 不支持 ❌ | 支持 ✅ |
| 统计分析 | 不支持 ❌ | 支持 ✅ |

---

## 🎉 总结

### 已解决的问题

✅ **重启后数据丢失** → 数据库持久化  
✅ **第二次处理识别为 CREATE** → 从数据库加载历史  
✅ **无审计追踪** → processing_history 表  
✅ **重复处理文档** → document_processing 表检查  
✅ **无法查询历史** → 按单据号/提单号查询  
✅ **无统计分析** → 数据库统计功能  

### 立即使用

```bash
# 启动应用
streamlit run app.py

# 步骤:
# 1. 勾选"启用数据库持久化"
# 2. 上传文档
# 3. 开始处理
# 4. 查看数据库统计
# 5. 重启应用，数据依然存在！
```

**项目现已完全支持生产环境的持久化需求！** 🎊
