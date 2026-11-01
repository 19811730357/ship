# 📊 数据库持久化解决方案

## 🎯 问题说明

### 当前问题

**场景重现**：
1. 第一次处理：BL-2024-001 的操作费 50 USD → 系统判断 **CREATE**
2. **重启应用**
3. 第二次处理：BL-2024-001 的操作费改为 30 USD → 系统又判断 **CREATE**（❌ 应该是 UPDATE）

**根本原因**：
- ❌ 没有持久化存储
- ❌ 每次重启后旧账数据丢失
- ❌ 无法追溯历史操作

### 生产环境需求

✅ **必须实现**：
1. 历史记录持久化
2. 单据号唯一性追踪
3. 操作审计日志
4. 支持增量更新（第二次处理同一单据应该是 UPDATE）

---

## 💡 解决方案

### 方案概述

使用 **SQLite（开发）或 PostgreSQL（生产）** 数据库存储：
- 账本记录（ledger_records）
- 处理历史（processing_history）
- 文档处理记录（document_processing）

### 数据库表设计

#### 1. ledger_records - 账本记录表
```sql
CREATE TABLE ledger_records (
    id INTEGER PRIMARY KEY,
    record_id TEXT UNIQUE NOT NULL,           -- 记录唯一ID
    document_number TEXT,                      -- 单据号
    bill_of_lading TEXT,                       -- 提单号
    charge_name TEXT NOT NULL,                 -- 费用名称
    standardized_name TEXT,                    -- 标准名称
    amount REAL NOT NULL,                      -- 金额
    currency TEXT NOT NULL,                    -- 币种
    payment_method TEXT,                       -- 付款方式
    posting_type TEXT,                         -- AR/AP
    accounting_entity TEXT NOT NULL,           -- 记账主体
    record_data TEXT,                          -- 完整JSON数据
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, -- 创建时间
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP  -- 更新时间
);
```

#### 2. processing_history - 处理历史表
```sql
CREATE TABLE processing_history (
    id INTEGER PRIMARY KEY,
    session_id TEXT,                           -- 会话ID
    operation TEXT NOT NULL,                   -- CREATE/UPDATE/NO_CHANGE
    record_id TEXT,                            -- 关联的记录ID
    model_suggestion TEXT,                     -- 模型建议
    model_confidence TEXT,                     -- 置信度
    model_reasoning TEXT,                      -- 决策理由
    program_validation TEXT,                   -- 程序验证结果
    final_decision TEXT,                       -- 最终决策
    decision_data TEXT,                        -- 完整决策JSON
    processed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### 3. document_processing - 文档处理表
```sql
CREATE TABLE document_processing (
    id INTEGER PRIMARY KEY,
    document_hash TEXT UNIQUE NOT NULL,        -- 文件指纹（SHA256）
    file_name TEXT,                            -- 文件名
    processing_status TEXT,                    -- 处理状态
    results TEXT,                              -- 处理结果JSON
    processed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🔧 实现步骤

### 步骤1：安装依赖

SQLite（已内置）无需额外安装。

PostgreSQL（生产环境）：
```bash
pip install psycopg2-binary
```

### 步骤2：使用数据库模块

**已创建文件**：`src/billing_agent/database.py`

**核心功能**：
- `save_ledger_record()` - 保存账本记录
- `load_ledger()` - 加载账本
- `save_processing_history()` - 保存处理历史
- `query_records_by_document()` - 按单据号查询
- `query_records_by_bl()` - 按提单号查询
- `check_document_processed()` - 检查文档是否已处理

### 步骤3：运行演示

```bash
python demo_database.py
```

**演示内容**：
1. 第一次处理：CREATE 操作费 50 USD
2. 保存到数据库
3. **模拟重启**
4. 从数据库加载旧账
5. 第二次处理：UPDATE 操作费为 30 USD
6. 验证正确识别为 UPDATE

---

## 📝 使用示例

### 示例1：基本使用

```python
from billing_agent.database import DatabaseManager
from billing_agent.agent import BillingAgent

# 1. 初始化数据库
db = DatabaseManager(db_type="sqlite", db_config={"database": "billing.db"})

# 2. 从数据库加载旧账（而不是空账本！）
ledger = db.load_ledger("Demo Company")

print(f"从数据库加载了 {len(ledger.records)} 条记录")

# 3. 处理新材料
agent = BillingAgent(accounting_entity="Demo Company", use_mock=False)
agent_batch = agent.process_material(material_content, ledger)

# 4. 保存结果到数据库
for decision in agent_batch.decisions:
    record = create_ledger_record_from_decision(decision)
    db.save_ledger_record(record)  # 持久化！

# 5. 下次重启后，数据依然存在
```

### 示例2：检查重复文档

```python
# 计算文件指纹
file_content = open("bill.pdf", "rb").read()
existing = db.check_document_processed(file_content)

if existing:
    print("文档已处理过，跳过")
    print(f"处理时间: {existing['processed_at']}")
else:
    # 处理新文档
    results = process_document(file_content)
    db.save_document_processing(file_content, "bill.pdf", "success", results)
```

### 示例3：查询历史

```python
# 按单据号查询
records = db.query_records_by_document("DN-2024-001")
for record in records:
    print(f"{record.charge_details.original_name}: {record.charge_details.amount}")

# 按提单号查询
records = db.query_records_by_bl("BL-2024-001")

# 获取统计
stats = db.get_processing_statistics("Demo Company")
print(f"总记录: {stats['total_records']}")
print(f"唯一单据: {stats['unique_documents']}")
```

---

## 🔄 完整工作流

### 修改前（无数据库）

```python
# workflow.py
ledger = Ledger(accounting_entity="Demo")  # ❌ 每次都是空的

agent_batch = agent.process_material(content, ledger)
# 处理完就丢了，重启后数据消失
```

### 修改后（有数据库）

```python
# workflow.py
db = DatabaseManager(db_type="sqlite", db_config={"database": "billing.db"})

# ✅ 从数据库加载历史数据
ledger = db.load_ledger(accounting_entity)

agent_batch = agent.process_material(content, ledger)

# ✅ 保存到数据库，重启后依然存在
for decision in agent_batch.decisions:
    record = create_record(decision)
    db.save_ledger_record(record)
```

---

## 🎯 效果对比

### 场景：处理同一单据两次

| | 无数据库 | 有数据库 |
|---|---|---|
| 第一次处理 | CREATE ✅ | CREATE ✅ |
| 重启应用 | 数据丢失 ❌ | 数据保留 ✅ |
| 第二次处理 | CREATE ❌（错误！） | UPDATE ✅（正确！） |
| 历史追溯 | 不支持 ❌ | 支持 ✅ |
| 审计日志 | 不支持 ❌ | 支持 ✅ |

---

## 🚀 集成到 Streamlit

### 修改 app.py

```python
# app.py
from billing_agent.database import DatabaseManager

# 初始化数据库（全局或 session_state）
if 'db' not in st.session_state:
    st.session_state.db = DatabaseManager(
        db_type="sqlite",
        db_config={"database": "billing.db"}
    )

# 处理文件时使用数据库
db = st.session_state.db

# 加载旧账
ledger = db.load_ledger(accounting_entity)

# 显示当前账本状态
st.info(f"当前账本有 {len(ledger.records)} 条记录")

# 处理完成后保存
for decision in agent_batch.decisions:
    record = create_record(decision)
    db.save_ledger_record(record)

st.success("已保存到数据库，重启后依然有效！")
```

---

## 📊 数据库管理

### 查看数据

**SQLite**（推荐工具：DB Browser for SQLite）
```bash
sqlite3 billing.db

# 查看记录
SELECT * FROM ledger_records;

# 查看统计
SELECT COUNT(*) FROM ledger_records;
SELECT COUNT(DISTINCT document_number) FROM ledger_records;
```

**PostgreSQL**
```bash
psql -d billing -U postgres

SELECT * FROM ledger_records;
```

### 备份数据

**SQLite**
```bash
# 备份
cp billing.db billing_backup_$(date +%Y%m%d).db

# 恢复
cp billing_backup_20241031.db billing.db
```

**PostgreSQL**
```bash
# 备份
pg_dump billing > billing_backup.sql

# 恢复
psql billing < billing_backup.sql
```

---

## 🎓 进阶功能

### 1. 版本控制

为每条记录保存历史版本：

```python
# 保存时记录版本
record.version = get_next_version(record_id)
db.save_ledger_record(record)

# 查询版本历史
versions = db.get_record_versions(record_id)
```

### 2. 软删除

标记删除而不是真删除：

```python
record.is_deleted = True
record.deleted_at = datetime.now()
db.save_ledger_record(record)
```

### 3. 并发控制

使用乐观锁：

```python
record.version += 1
try:
    db.update_with_version_check(record)
except VersionConflictError:
    # 记录已被其他用户修改
    pass
```

---

## ✅ 总结

### 问题解决

✅ **重启后数据丢失** → 数据库持久化  
✅ **无法识别 UPDATE** → 从数据库加载历史  
✅ **无审计追踪** → processing_history 表  
✅ **重复处理** → document_processing 表检查  

### 下一步

1. **开发环境**：使用 SQLite（已实现）
2. **生产环境**：切换到 PostgreSQL
3. **集成到前端**：修改 app.py 使用数据库
4. **添加功能**：版本控制、软删除、并发控制

### 运行测试

```bash
# 运行数据库演示
python demo_database.py

# 查看生成的数据库文件
ls -lh billing.db
```

**项目现在支持数据库持久化，解决了重启丢失数据的问题！** 🎉
