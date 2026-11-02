# MySQL 数据库集成指南

## 📊 连接到你的 MySQL `ship` 数据库

你截图中显示的是 **Navicat 中的 MySQL `ship` 数据库**。现在系统已支持连接到这个数据库。

---

## 🚀 快速开始

### 步骤1：安装 MySQL 驱动

```bash
conda activate ship_env
pip install pymysql
```

### 步骤2：配置数据库连接

编辑 `.env` 文件，添加 MySQL 配置：

```bash
# MySQL 数据库配置
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_NAME=ship
DB_USER=root
DB_PASSWORD=你的MySQL密码
```

### 步骤3：测试连接

```bash
python test_mysql_connection.py
```

**预期输出**：
```
======================================================================
MySQL Connection Test
======================================================================

Connecting to MySQL:
  Host: localhost:3306
  Database: ship
  User: root

[OK] Connected to MySQL successfully!
[OK] Tables created/verified
[OK] Test record saved
[OK] Loaded 1 records from database

[SUCCESS] MySQL integration working!
```

### 步骤4：在 Streamlit 中使用

启动应用后，侧边栏会显示：
```
💾 数据库配置
✅ 数据库已启用
数据库类型: MySQL
数据库: ship @ localhost:3306
```

---

## 📋 创建的表结构

系统会在 `ship` 数据库中自动创建以下表：

### 1. ledger_records（账本记录表）

```sql
CREATE TABLE ledger_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    record_id VARCHAR(50) UNIQUE NOT NULL,
    document_number VARCHAR(100),
    bill_of_lading VARCHAR(100),
    charge_name VARCHAR(200) NOT NULL,
    standardized_name VARCHAR(200),
    amount DECIMAL(15, 2) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    payment_method VARCHAR(50),
    posting_type VARCHAR(10),
    accounting_entity VARCHAR(200) NOT NULL,
    record_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_document_number (document_number),
    INDEX idx_bill_of_lading (bill_of_lading),
    INDEX idx_record_id (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 2. processing_history（处理历史表）

```sql
CREATE TABLE processing_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(50),
    operation VARCHAR(20) NOT NULL,
    record_id VARCHAR(50),
    model_suggestion VARCHAR(20),
    model_confidence VARCHAR(20),
    model_reasoning TEXT,
    program_validation VARCHAR(20),
    final_decision VARCHAR(20),
    decision_data TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (record_id) REFERENCES ledger_records(record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3. document_processing（文档处理表）

```sql
CREATE TABLE document_processing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    document_hash VARCHAR(64) UNIQUE NOT NULL,
    file_name VARCHAR(255),
    processing_status VARCHAR(20),
    results TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 🔧 在 Streamlit 中配置

修改 `app.py` 中的数据库配置读取：

```python
# 从环境变量读取数据库配置
import os
from dotenv import load_dotenv

load_dotenv()

db_type = os.getenv("DB_TYPE", "sqlite")
db_config = {}

if db_type == "mysql":
    db_config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 3306)),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "ship")
    }
    st.sidebar.info(f"📊 MySQL: {db_config['database']} @ {db_config['host']}")
elif db_type == "sqlite":
    db_config = {"database": os.getenv("DB_DATABASE", "billing.db")}
    st.sidebar.info(f"📁 SQLite: {db_config['database']}")

# 创建工作流
workflow = DatabaseWorkflow(
    accounting_entity=accounting_entity,
    use_mock_data=False,
    db_type=db_type,
    db_config=db_config
)
```

---

## 🔍 在 Navicat 中查看数据

连接后，你可以在 Navicat 中看到新创建的表：

```
ship
├── 表
│   ├── ledger_records         ← 账本记录
│   ├── processing_history     ← 处理历史
│   └── document_processing    ← 文档记录
├── 视图
├── 函数
└── 查询
```

### 查询示例

**查看所有记录**：
```sql
SELECT * FROM ledger_records ORDER BY created_at DESC;
```

**按单据号查询**：
```sql
SELECT * FROM ledger_records WHERE document_number = 'DN-2024-001';
```

**统计数据**：
```sql
SELECT 
    COUNT(*) as total_records,
    COUNT(DISTINCT document_number) as unique_docs,
    COUNT(DISTINCT bill_of_lading) as unique_bls
FROM ledger_records;
```

**查看最近的处理历史**：
```sql
SELECT 
    operation,
    model_suggestion,
    model_confidence,
    final_decision,
    processed_at
FROM processing_history
ORDER BY processed_at DESC
LIMIT 10;
```

---

## 🎯 SQLite vs MySQL 对比

| 特性 | SQLite | MySQL |
|------|--------|-------|
| 部署 | 无需服务器 | 需要 MySQL 服务器 |
| 并发 | 单用户 | 多用户支持 |
| 适用场景 | 开发、测试、单机 | 生产、多用户、大数据 |
| 数据文件 | billing.db | ship 数据库 |
| 备份 | 复制文件 | mysqldump |
| 性能 | 小数据量快 | 大数据量优势 |
| 事务 | 支持 | 支持 |

---

## ⚙️ 配置选项

### 选项1：使用 SQLite（默认）

```bash
# .env
DB_TYPE=sqlite
DB_DATABASE=billing.db
```

### 选项2：使用 MySQL（你的 ship 数据库）

```bash
# .env
DB_TYPE=mysql
DB_HOST=localhost
DB_PORT=3306
DB_NAME=ship
DB_USER=root
DB_PASSWORD=your_password
```

### 选项3：使用 PostgreSQL（生产环境推荐）

```bash
# .env
DB_TYPE=postgres
DB_HOST=localhost
DB_PORT=5432
DB_NAME=billing
DB_USER=postgres
DB_PASSWORD=your_password
```

---

## 🛠️ 故障排查

### 问题1：连接失败

**错误**：`Can't connect to MySQL server`

**解决**：
1. 确认 MySQL 服务已启动
2. 检查防火墙设置
3. 验证用户名和密码

### 问题2：权限不足

**错误**：`Access denied for user`

**解决**：
```sql
-- 授予权限
GRANT ALL PRIVILEGES ON ship.* TO 'root'@'localhost';
FLUSH PRIVILEGES;
```

### 问题3：数据库不存在

**错误**：`Unknown database 'ship'`

**解决**：
```sql
-- 创建数据库
CREATE DATABASE ship CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 问题4：pymysql 未安装

**错误**：`No module named 'pymysql'`

**解决**：
```bash
pip install pymysql
```

---

## 📊 数据迁移

### 从 SQLite 迁移到 MySQL

```python
from billing_agent.database import DatabaseManager

# 1. 从 SQLite 加载数据
sqlite_db = DatabaseManager(db_type="sqlite", db_config={"database": "billing.db"})
ledger = sqlite_db.load_ledger("Demo Company")

# 2. 连接到 MySQL
mysql_db = DatabaseManager(db_type="mysql", db_config={
    "host": "localhost",
    "database": "ship",
    "user": "root",
    "password": "your_password"
})

# 3. 保存到 MySQL
for record in ledger.records:
    mysql_db.save_ledger_record(record)

print(f"Migrated {len(ledger.records)} records to MySQL")
```

---

## ✅ 验证集成

运行完整测试：

```bash
# 1. 测试 MySQL 连接
python test_mysql_connection.py

# 2. 运行应用
streamlit run app.py

# 3. 上传文档并处理

# 4. 在 Navicat 中查看数据
```

在 Navicat 中应该能看到：
- `ledger_records` 表有新记录
- `processing_history` 表有处理历史
- `document_processing` 表有文档记录

---

## 🎉 总结

现在系统支持：
- ✅ SQLite（默认，无需配置）
- ✅ MySQL（你的 ship 数据库）
- ✅ PostgreSQL（生产环境）

根据你的需求选择合适的数据库类型！
