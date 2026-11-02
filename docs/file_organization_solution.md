# 📁 文件组织与索引方案

## 🔍 当前处理方式

### 现状分析

**当前数据库结构**：
```
ledger_records (账本记录)
├── record_id (记录ID)
├── document_number (单据号)
├── bill_of_lading (提单号)
├── charge_name (费用名称)
├── accounting_entity (记账主体)
└── ...

document_processing (文档处理记录)
├── document_hash (文件SHA256)
├── file_name (文件名)
└── ...
```

**问题**：
- ❌ 没有文件夹/项目概念
- ❌ 不同客户/项目的数据混在一起
- ❌ 无法按业务维度组织数据
- ❌ 难以权限管理

---

## 💡 改进方案：多级索引体系

### 方案1：添加项目/客户维度（推荐）✅

#### 新增表结构

```sql
-- 1. 项目/客户表
CREATE TABLE projects (
    project_id VARCHAR(50) PRIMARY KEY,
    project_name VARCHAR(200) NOT NULL,
    client_name VARCHAR(200),
    project_type VARCHAR(50),  -- 进口/出口/内贸
    status VARCHAR(20),  -- active/archived
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    metadata TEXT,  -- JSON格式的额外信息
    INDEX idx_client_name (client_name),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 文档目录表
CREATE TABLE document_catalog (
    catalog_id VARCHAR(50) PRIMARY KEY,
    project_id VARCHAR(50) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500),
    file_hash VARCHAR(64) UNIQUE,
    file_size BIGINT,
    file_type VARCHAR(20),  -- eml, pdf, docx, xlsx
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE,
    processing_status VARCHAR(20),  -- pending/processing/completed/failed
    session_id VARCHAR(50),
    metadata TEXT,  -- JSON格式
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    INDEX idx_project_id (project_id),
    INDEX idx_file_hash (file_hash),
    INDEX idx_processing_status (processing_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 修改 ledger_records 表，添加项目关联
ALTER TABLE ledger_records 
ADD COLUMN project_id VARCHAR(50),
ADD COLUMN catalog_id VARCHAR(50),
ADD INDEX idx_project_id (project_id),
ADD INDEX idx_catalog_id (catalog_id),
ADD FOREIGN KEY (project_id) REFERENCES projects(project_id),
ADD FOREIGN KEY (catalog_id) REFERENCES document_catalog(catalog_id);
```

#### 数据层次结构

```
Projects (项目)
  └── 项目A (马士基-进口业务)
      ├── Document Catalog (文档目录)
      │   ├── 2024-10-01_bill.eml
      │   ├── 2024-10-02_invoice.pdf
      │   └── 2024-10-03_debit_note.docx
      └── Ledger Records (账本记录)
          ├── 记录1: 操作费 50 USD (来自 bill.eml)
          ├── 记录2: 文件费 30 USD (来自 bill.eml)
          └── 记录3: 码头费 120 USD (来自 invoice.pdf)

  └── 项目B (中远-出口业务)
      ├── Document Catalog
      └── Ledger Records
```

---

### 方案2：文件夹树形结构

#### 树形目录表

```sql
-- 文件夹树形结构
CREATE TABLE folders (
    folder_id VARCHAR(50) PRIMARY KEY,
    parent_id VARCHAR(50),  -- NULL表示根目录
    folder_name VARCHAR(200) NOT NULL,
    folder_path VARCHAR(1000),  -- 完整路径，如 /客户A/2024年/10月
    level INT,  -- 层级深度
    accounting_entity VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,
    FOREIGN KEY (parent_id) REFERENCES folders(folder_id),
    INDEX idx_parent_id (parent_id),
    INDEX idx_folder_path (folder_path(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 文档关联到文件夹
ALTER TABLE document_catalog 
ADD COLUMN folder_id VARCHAR(50),
ADD FOREIGN KEY (folder_id) REFERENCES folders(folder_id);
```

#### 使用示例

```
根目录 (/)
├── 客户A (folder_id: F001)
│   ├── 2024年 (folder_id: F002)
│   │   ├── 10月 (folder_id: F003)
│   │   │   ├── bill_001.eml
│   │   │   └── bill_002.eml
│   │   └── 11月 (folder_id: F004)
│   └── 2023年 (folder_id: F005)
└── 客户B (folder_id: F006)
```

---

### 方案3：标签系统（灵活但复杂）

```sql
-- 标签表
CREATE TABLE tags (
    tag_id VARCHAR(50) PRIMARY KEY,
    tag_name VARCHAR(100) NOT NULL UNIQUE,
    tag_category VARCHAR(50),  -- 客户/项目/类型/年份
    tag_color VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 文档-标签关联表
CREATE TABLE document_tags (
    document_hash VARCHAR(64),
    tag_id VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_hash, tag_id),
    FOREIGN KEY (document_hash) REFERENCES document_catalog(file_hash),
    FOREIGN KEY (tag_id) REFERENCES tags(tag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 🎯 推荐实施方案

### 阶段1：添加项目维度（最简单）✅

#### 1.1 创建项目表

```python
# src/billing_agent/database.py

def _init_tables(self):
    # ... 现有表 ...
    
    if self.db_type == "mysql":
        # 项目表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id VARCHAR(50) PRIMARY KEY,
                project_name VARCHAR(200) NOT NULL,
                client_name VARCHAR(200),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_client (client_name),
                INDEX idx_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        # 文档目录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_catalog (
                catalog_id VARCHAR(50) PRIMARY KEY,
                project_id VARCHAR(50) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                file_hash VARCHAR(64) UNIQUE,
                file_type VARCHAR(20),
                upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processing_status VARCHAR(20) DEFAULT 'pending',
                FOREIGN KEY (project_id) REFERENCES projects(project_id),
                INDEX idx_project (project_id),
                INDEX idx_hash (file_hash)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
```

#### 1.2 修改工作流

```python
# workflow_db.py

class DatabaseWorkflow:
    def __init__(
        self, 
        accounting_entity: str,
        project_id: Optional[str] = None,  # 新增
        project_name: Optional[str] = None,  # 新增
        ...
    ):
        self.project_id = project_id or self._create_default_project()
        
    def _create_default_project(self):
        """创建默认项目"""
        project_id = f"PRJ-{uuid.uuid4().hex[:8]}"
        # 保存到数据库
        return project_id
        
    def process_real_files(self, file_paths, ...):
        # 1. 注册文档到目录
        for file_path in file_paths:
            catalog_id = self._register_document(file_path)
            
        # 2. 处理文件（关联 catalog_id）
        # ...
        
    def _register_document(self, file_path: Path) -> str:
        """注册文档到目录"""
        catalog_id = f"CAT-{uuid.uuid4().hex[:8]}"
        file_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        
        cursor = self.db.conn.cursor()
        cursor.execute("""
            INSERT INTO document_catalog 
            (catalog_id, project_id, file_name, file_hash, file_type)
            VALUES (%s, %s, %s, %s, %s)
        """, (catalog_id, self.project_id, file_path.name, file_hash, file_path.suffix))
        
        self.db.conn.commit()
        return catalog_id
```

#### 1.3 前端选择项目

```python
# app.py

st.sidebar.subheader("📁 项目选择")

# 获取项目列表
projects = db.get_projects()

if projects:
    project_options = {p['project_name']: p['project_id'] for p in projects}
    selected_project = st.sidebar.selectbox(
        "选择项目",
        options=list(project_options.keys())
    )
    project_id = project_options[selected_project]
else:
    # 创建新项目
    new_project_name = st.sidebar.text_input("项目名称", value="默认项目")
    project_id = None

# 使用项目
workflow = DatabaseWorkflow(
    accounting_entity=accounting_entity,
    project_id=project_id,
    project_name=new_project_name,
    ...
)
```

---

## 📊 查询示例

### 按项目查询

```sql
-- 查询某个项目的所有记录
SELECT 
    lr.*,
    dc.file_name,
    p.project_name
FROM ledger_records lr
JOIN document_catalog dc ON lr.catalog_id = dc.catalog_id
JOIN projects p ON lr.project_id = p.project_id
WHERE p.project_id = 'PRJ-abc123'
ORDER BY lr.created_at DESC;
```

### 按客户查询

```sql
-- 查询某个客户的所有项目和记录
SELECT 
    p.project_name,
    COUNT(DISTINCT dc.catalog_id) as document_count,
    COUNT(lr.record_id) as record_count,
    SUM(lr.amount) as total_amount
FROM projects p
LEFT JOIN document_catalog dc ON p.project_id = dc.project_id
LEFT JOIN ledger_records lr ON p.project_id = lr.project_id
WHERE p.client_name = '马士基'
GROUP BY p.project_id;
```

### 按时间查询

```sql
-- 查询本月处理的文档
SELECT 
    p.project_name,
    dc.file_name,
    dc.processing_status,
    dc.upload_time
FROM document_catalog dc
JOIN projects p ON dc.project_id = p.project_id
WHERE dc.upload_time >= DATE_FORMAT(NOW(), '%Y-%m-01')
ORDER BY dc.upload_time DESC;
```

---

## 🎨 前端展示

### 项目视图

```
📁 项目管理
├── 🏢 马士基-进口业务 (PRJ-001)
│   ├── 📄 文档: 15 个
│   ├── 💰 记录: 45 条
│   └── 💵 总金额: $12,500
│
├── 🏢 中远-出口业务 (PRJ-002)
│   ├── 📄 文档: 8 个
│   ├── 💰 记录: 24 条
│   └── 💵 总金额: $8,300
│
└── ➕ 创建新项目
```

### 文档目录视图

```
📂 马士基-进口业务
├── 📧 2024-10-01_bill.eml ✅ (3条记录)
├── 📄 2024-10-02_invoice.pdf ✅ (2条记录)
├── 📄 2024-10-03_debit.docx ⏳ (处理中)
└── 📧 2024-10-04_notice.eml ❌ (失败)
```

---

## 🔒 权限控制（可选）

```sql
-- 用户表
CREATE TABLE users (
    user_id VARCHAR(50) PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    role VARCHAR(20)  -- admin/manager/viewer
);

-- 项目权限表
CREATE TABLE project_permissions (
    user_id VARCHAR(50),
    project_id VARCHAR(50),
    permission VARCHAR(20),  -- read/write/admin
    PRIMARY KEY (user_id, project_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);
```

---

## ✅ 实施步骤

### 第1步：数据库升级（30分钟）
1. 创建 `projects` 表
2. 创建 `document_catalog` 表
3. 修改 `ledger_records` 表（添加外键）

### 第2步：代码修改（1小时）
1. 修改 `DatabaseManager`（添加项目相关方法）
2. 修改 `DatabaseWorkflow`（支持项目参数）
3. 添加文档注册逻辑

### 第3步：前端更新（1小时）
1. 添加项目选择器
2. 添加项目创建界面
3. 显示项目统计信息

### 第4步：数据迁移（可选）
1. 为现有记录创建默认项目
2. 更新外键关联

---

## 🎯 最终效果

### 用户体验
```
1. 登录系统
2. 选择/创建项目：「马士基-2024年10月」
3. 上传文档到该项目
4. 系统自动:
   - 记录文档到目录
   - 处理并生成记录
   - 关联到项目
5. 查询时按项目过滤
6. 导出时包含项目信息
```

### 数据组织
```
✅ 清晰的项目划分
✅ 完整的文档追溯
✅ 灵活的查询维度
✅ 便于权限管理
✅ 支持业务扩展
```

---

**推荐从"方案1：项目维度"开始，简单有效！** 🎉
