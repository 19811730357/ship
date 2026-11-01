# 🚢 航运智能账单助手 V2

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![LangChain](https://img.shields.io/badge/LangChain-0.1+-green.svg)](https://www.langchain.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-red.svg)](https://streamlit.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于大模型决策的智能航运账单处理系统，采用**模型主导决策 + 程序验证保障**的创新架构。

## ✨ 核心特性

- 🤖 **模型主导决策**：大模型理解语义并给出 CRUD 操作建议
- 🔍 **程序验证保障**：独立验证模型决策，确保数据可靠性
- ⚖️ **智能冲突解决**：模型与程序判断不一致时自动处理
- 📊 **完整审计追踪**：记录决策过程、冲突解决和证据链
- 🎯 **即用演示场景**：4个典型场景，无需配置即可体验

## 🎯 快速开始

### 1️⃣ 环境准备

```bash
# 创建虚拟环境
conda create -n ship_env python=3.11 -y
conda activate ship_env

# 安装依赖
pip install -r requirements.txt
```

### 2️⃣ 启动应用

**方式 A - 使用启动脚本（推荐）**
```bash
# Windows
双击 start.bat

# 或命令行
start.bat
```

**方式 B - 命令行启动**
```bash
streamlit run app.py
```

### 3️⃣ 访问界面

浏览器自动打开：http://localhost:8501

## 🎬 演示场景

系统内置 4 个典型场景，无需配置 API 即可体验完整功能：

| 场景 | 说明 | 模型决策 | 程序验证 | 最终结果 |
|------|------|----------|----------|----------|
| **明确更新** | 邮件明确说"将操作费从50美元改为40美元" | UPDATE（高置信度） | 一致通过 | ✅ UPDATE |
| **同名费用歧义** | 旧账中有两条 HANDLING CHARGE（65和35美元） | UPDATE（但无法确定哪条） | 发现多个候选 | ⚠️ PENDING_REVIEW |
| **新增费用** | 新单据中的 THC 费用，旧账中没有 | CREATE（高置信度） | 确认无匹配 | ✅ CREATE |
| **条件收费** | 文档包含"如超期则收取滞期费"的条款 | 识别条件条款并排除 | 通过 | ✅ 排除条件条款 |

## 📁 项目结构

```
shipping-billing-agent-v2/
├── src/billing_agent/          # 核心业务逻辑
│   ├── models.py              # Pydantic 数据模型
│   ├── agent.py               # LangChain Agent 框架
│   ├── validator.py           # 程序验证器
│   ├── ledger.py              # 账本管理和冲突解决
│   ├── workflow.py            # 完整工作流
│   ├── demo.py                # 演示场景数据
│   ├── parsers.py             # 文件解析器
│   └── integrations.py        # OCR/OSS 适配器
│
├── tests/                      # 单元测试
│   ├── test_models.py
│   ├── test_validator.py
│   └── test_ledger.py
│
├── docs/                       # 文档
│   ├── architecture.md        # 架构说明
│   ├── design_decisions.md    # 设计决策
│   └── api_guide.md           # API 配置指南
│
├── output/                     # 输出目录
├── app.py                      # Streamlit Web 界面
├── start.bat                   # 快速启动脚本
├── requirements.txt            # Python 依赖
├── .env.example                # 配置模板
└── README.md                   # 项目说明
```

## 🔑 配置真实 API

### 步骤 1：配置密钥

```bash
# 1. 复制配置模板
cp .env.example .env

# 2. 编辑 .env 文件，填写 API 密钥
DASHSCOPE_API_KEY=sk-your-actual-key-here

# 3. 设置使用真实 API
USE_MOCK_DATA=false
```

### 步骤 2：获取千问 API 密钥

1. 访问：https://dashscope.console.aliyun.com/
2. 登录/注册阿里云账号
3. 创建 API 密钥
4. 复制密钥（以 sk- 开头）

### 步骤 3：重启应用

配置完成后重新启动应用即可使用真实模型。

## 🏗️ 核心设计

### 决策流程

```
材料 + 旧账
    ↓
┌─────────────────┐
│  Agent 决策     │ ← 模型理解语义，给出操作建议
│  suggested_op   │   CREATE / UPDATE / NO_CHANGE
│  reasoning      │   决策理由
│  confidence     │   HIGH / MEDIUM / LOW
└────────┬────────┘
         ↓
┌─────────────────┐
│  程序验证       │ ← 独立验证模型决策
│  独立匹配       │   金额格式、币种、AR/AP
│  规则检查       │   匹配旧账、操作合理性
└────────┬────────┘
         ↓
┌─────────────────┐
│  冲突解决       │ ← 智能合并
│  一致→采纳      │   模型 vs 程序
│  冲突→复核      │   高置信度可信任模型
└────────┬────────┘
         ↓
┌─────────────────┐
│  最终操作       │
│  + 完整审计     │
└─────────────────┘
```

### 与传统方案对比

| 维度 | V1（传统） | V2（本系统）✨ |
|------|-----------|---------------|
| Agent 职责 | 仅提取信息 | **决策操作** + 理由 + 证据 |
| 程序职责 | 决定一切 | **验证保障** + 安全网 |
| 冲突处理 | 无 | **双重判断** + 智能合并 |
| 模型能力 | 低 | **充分利用** 语义理解 |
| 可解释性 | 程序规则 | **完整追踪** 决策过程 |

## 📊 输出文件

每次处理生成 3 个 JSON 文件：

### 1. processing_results.json
每个费用的详细处理结果：
- 操作类型（CREATE/UPDATE/NO_CHANGE/PENDING_REVIEW）
- 模型决策（建议、理由、置信度）
- 程序验证（验证结果、发现的问题）
- 冲突解决（如何处理不一致）
- 完整的业务数据和证据

### 2. ledger_snapshot.json
合并变更后的完整账本：
- 所有账本记录
- 审计历史
- 版本号
- 已应用的操作 ID

### 3. run_report.json
运行报告：
- 文件处理统计
- 操作类型分布
- 排除项列表
- API 调用状态
- 错误记录

## 🧪 运行测试

```bash
# 激活环境
conda activate ship_env

# 运行所有测试
pytest tests/ -v

# 运行覆盖率测试
pytest tests/ --cov=src/billing_agent --cov-report=html

# 查看覆盖率报告
# 打开 htmlcov/index.html
```

## 🎓 核心设计理念

### 为什么让模型决策操作？

**问题**：传统方案中，模型只提取信息，程序决定操作。这样的话，为什么要用"智能"助手？

**答案**：
- ✅ 模型能理解"修改为"、"调整"等复杂语义
- ✅ 能处理"上月的操作费"等引用
- ✅ 能识别条件条款 vs 实际费用
- ✅ 这才是真正的"智能"

### 为什么保留程序验证？

**问题**：如果信任模型，为什么还要程序验证？

**答案**：
- ✅ 模型可能判断错误
- ✅ 金额、币种等需要精确验证
- ✅ 程序作为安全网，不一致时转人工
- ✅ 双重判断增强可信度

## 🚀 技术栈

- **LLM 框架**：LangChain
- **模型**：阿里云通义千问（OpenAI 兼容接口）
- **数据验证**：Pydantic V2
- **Web 界面**：Streamlit
- **精确计算**：Python Decimal
- **测试**：Pytest

## 📚 详细文档

详细文档位于 `docs/` 目录：

- [**architecture.md**](docs/architecture.md) - 完整的系统架构说明
- [**design_decisions.md**](docs/design_decisions.md) - 关键设计决策的详细讨论
- [**api_guide.md**](docs/api_guide.md) - API 配置的完整指南

## 🎉 项目亮点总结

1. **创新架构** - 模型主导决策，程序验证保障
2. **双重判断** - 模型和程序独立判断，智能合并
3. **完整追踪** - 每个决策都有理由、证据和冲突解决过程
4. **即用演示** - 4 个典型场景，无需配置即可体验
5. **详尽文档** - 架构、设计决策、API 配置全覆盖
6. **可扩展性** - 清晰的模块边界，易于后续开发

## 📝 开发路线

### 已完成 ✅
- 核心数据模型
- 模型决策框架
- 程序验证器
- 冲突解决逻辑
- 完整工作流
- 4 个演示场景
- Web 界面
- 文档和测试

### 待完善 🔨
- **真实文件解析**（parsers.py）
  - EML 邮件解析
  - PDF/图片 OCR 集成
  - Excel/Word 解析

- **Agent 真实调用**（agent.py）
  - 完整的 LangChain 集成
  - 结构化输出调试
  - 提示词优化

- **外部服务集成**（integrations.py）
  - OCR 服务调用
  - OSS 文件上传
  - LibreOffice 转换

## 💡 使用建议

### 首次使用
1. 先运行**模拟演示**，熟悉功能
2. 查看 4 个场景的完整决策过程
3. 理解模型决策 vs 程序验证的机制

### 配置真实 API
1. 按照 `docs/api_guide.md` 配置千问密钥
2. 先用简单材料测试
3. 查看处理结果和审计追踪

### 遇到问题
1. 查看应用界面的详细信息
2. 检查 `output/` 目录的 JSON 输出
3. 参考 `docs/` 中的文档
4. 设置 `DEBUG=true` 查看详细日志

## 📄 许可证

MIT License

## 📞 联系与支持

- **文档**：查看 `docs/` 目录
- **示例**：运行演示场景了解功能
- **问题**：检查输出的 JSON 文件和日志

---

**祝使用愉快！** 🎊
