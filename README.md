# 航运智能账单助手 V2

基于大模型决策的智能航运账单处理系统。

## 核心特性

- **模型主导决策**：大模型理解原文语义并给出CRUD操作建议
- **程序验证保障**：程序独立验证模型决策，确保数据可靠性
- **冲突解决机制**：模型和程序判断不一致时，智能转人工复核
- **完整审计追踪**：记录决策过程、冲突解决和证据链

## 架构设计

### 与传统方案的区别

| 方面 | 传统方案 | 本系统 |
|------|----------|--------|
| 操作决策 | 程序规则决定 | 模型给出建议，程序验证 |
| Agent职责 | 仅信息提取 | 语义理解 + 操作建议 |
| 冲突处理 | 无 | 双重判断，不一致转复核 |

### 核心流程

```
材料解析 → Agent决策 → 程序验证 → 冲突解决 → 最终操作
           ↓              ↓             ↓
        操作建议      独立验证      智能合并
        +证据         +规则检查     +审计追踪
```

## 快速开始

### 1. 环境准备

使用Conda创建虚拟环境：

```bash
conda create -n ship_env python=3.11 -y
conda activate ship_env
```

### 2. 安装依赖

```bash
cd shipping-billing-agent-v2
pip install -r requirements.txt
```

### 3. 配置API密钥

复制配置模板并填写API密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写千问API密钥：

```bash
DASHSCOPE_API_KEY=your_actual_api_key_here
```

### 4. 运行演示

启动Streamlit界面：

```bash
streamlit run app.py
```

浏览器访问：http://localhost:8501

## 使用模拟数据测试

首次使用建议先运行模拟演示，不需要配置真实API：

1. 确保 `.env` 中 `USE_MOCK_DATA=true`
2. 运行Streamlit应用
3. 选择"模拟演示模式"
4. 依次测试四个场景：
   - 明确更新：修改金额，其他字段保留
   - 同名费用歧义：多条旧账无法唯一匹配
   - 新增费用：无旧账匹配，创建新记录
   - 条件收费：识别并排除未发生的条件条款

## 使用真实文件处理

配置真实API后：

1. 设置 `.env` 中 `USE_MOCK_DATA=false`
2. 配置 `DASHSCOPE_API_KEY`
3. （可选）配置OCR和OSS服务
4. 上传材料文件（EML、PDF、Excel、Word等）
5. 导入旧账JSON（或使用空账本）
6. 指定记账主体
7. 点击处理

## 输出文件

| 文件 | 说明 |
|------|------|
| `processing_results.json` | 每个费用的操作类型、模型决策、验证结果、冲突解决 |
| `ledger_snapshot.json` | 合并变更后的完整账本快照 |
| `run_report.json` | 文件处理状态、排除项、统计信息 |

## 项目结构

```
shipping-billing-agent-v2/
├── src/billing_agent/
│   ├── models.py          # Pydantic数据模型
│   ├── agent.py           # LangChain Agent（决策型）
│   ├── validator.py       # 程序验证规则
│   ├── ledger.py          # 旧账匹配和冲突解决
│   ├── workflow.py        # 完整处理流程
│   ├── parsers.py         # 文件解析器
│   ├── integrations.py    # OCR/OSS适配器
│   └── demo.py            # 模拟数据
├── tests/                 # 单元测试
├── examples/              # 示例数据
├── docs/                  # 文档
└── output/                # 输出目录
```

## 核心设计亮点

### 1. 模型决策能力

模型不仅提取信息，还能：
- 理解"修改"、"调整"、"取消"等修改意图
- 处理复杂引用（如"上月的操作费"）
- 识别条件条款 vs 实际费用
- 给出操作建议和置信度

### 2. 双重验证机制

```python
# 模型决策
model_op = "UPDATE"
model_confidence = "HIGH"

# 程序独立验证
program_op = "PENDING_REVIEW"  # 发现歧义

# 冲突解决
if model_confidence == "HIGH":
    final_op = "UPDATE"  # 信任高置信度模型
else:
    final_op = "PENDING_REVIEW"  # 谨慎处理
```

### 3. 完整审计追踪

每个操作记录：
- 模型的决策理由（`operation_reasoning`）
- 程序的验证结果（`validation_issues`）
- 冲突解决策略（`conflict_resolution`）
- 原文证据（`evidence`）

## 测试

运行单元测试：

```bash
pytest tests/ -v
```

运行覆盖率测试：

```bash
pytest tests/ --cov=src/billing_agent --cov-report=html
```

## 文档

详细文档位于 `docs/` 目录：

- `architecture.md` - 架构说明
- `design_decisions.md` - 设计决策记录
- `api_guide.md` - API配置指南

## 技术栈

- **LLM框架**：LangChain
- **模型**：阿里云通义千问（OpenAI兼容接口）
- **数据验证**：Pydantic V2
- **Web界面**：Streamlit
- **精确计算**：Python Decimal
- **测试**：Pytest

## 许可证

MIT License

## 联系方式

如有问题，请查看文档或提交Issue。
