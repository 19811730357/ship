# 🎯 完整调试和使用指南

## 项目状态：✅ 100% 完成

所有核心功能已实现并可用。

---

## 📍 查看 OCR 和模型数据流

### 方法1：运行调试脚本（推荐）

```bash
# 激活环境
conda activate ship_env

# 运行测试脚本
python test_ocr_debug.py
```

**查看内容**：
- 模拟的 OCR 识别内容
- 传递给模型的完整文本
- 模型返回的决策结果

**控制台输出示例**：
```
===================================================================
📄 传递给模型的材料内容:
===================================================================
航运账单
提单号: BL-2024-001
费用明细:
1. 操作费 (HANDLING CHARGE): 50.00 USD
...
===================================================================
🤖 模型返回结果:
===================================================================
{
  "decisions": [
    {
      "suggested_operation": "CREATE",
      "operation_reasoning": "这是新的费用...",
      ...
    }
  ]
}
===================================================================
```

### 方法2：Streamlit 应用查看

```bash
streamlit run app.py
```

1. 选择"真实文件处理"模式
2. 上传文档
3. 查看结果展示（包含模型决策理由）
4. 下载 JSON 文件查看详细数据

---

## 🔍 关键数据查看位置

### 1. OCR 识别结果

**文件**：`src/billing_agent/parsers.py`  
**位置**：第 315 行 `parse_file_from_url()`

```python
# 在这里可以看到 OCR API 返回的原始数据
ocr_result = self.ocr_adapter.process_file(file_url)
print("OCR返回:", ocr_result)
```

### 2. 传递给模型的内容

**文件**：`src/billing_agent/agent.py`  
**位置**：第 226 行（已添加 print 输出）

```python
# 控制台会打印：
# - 材料内容（包含 OCR 识别的文字）
# - 旧账摘要
print("传递给模型的内容:", material_content)
```

### 3. 模型返回结果

**文件**：`src/billing_agent/agent.py`  
**位置**：第 237 行（已添加 print 输出）

```python
# 控制台会打印模型的决策结果
response = self.chain.invoke({...})
print("模型返回:", response)
```

---

## 🚀 三种使用模式

### 模式1：演示模式（无需配置）

```bash
streamlit run app.py
```
- 选择"模拟演示"
- 运行 4 个预设场景
- 查看完整的决策过程

### 模式2：真实文件 + 模型（需要 API key）

**配置**：
```bash
# .env 文件
DASHSCOPE_API_KEY=sk-你的密钥
```

**使用**：
```bash
streamlit run app.py
```
- 选择"真实文件处理"
- 上传 Word/Excel/PDF（文字型）
- 查看模型分析结果

### 模式3：OCR + 模型（需要 API + OSS）

**配置**：
```bash
# .env 文件
DASHSCOPE_API_KEY=sk-你的密钥
OCR_URL=https://gateway.pltplt.com/ai/process
OSS_ACCESS_KEY_ID=你的key
OSS_ACCESS_KEY_SECRET=你的secret
OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com
OSS_BUCKET=你的bucket
```

**使用**：
- 上传扫描件 PDF 或图片
- 系统自动 OCR 识别
- 模型分析 OCR 结果

---

## 📊 查看结果的三种方式

### 1. 控制台输出
运行 `test_ocr_debug.py` 或 `streamlit run app.py`，查看终端打印

### 2. HTML 报告
```bash
# 生成报告
python generate_report.py

# 打开查看
demo_report.html
```

### 3. JSON 文件
```
output/
├── update/
│   ├── processing_results.json  ← 详细决策过程
│   ├── ledger_snapshot.json     ← 账本快照
│   └── run_report.json          ← 运行统计
├── ambiguous/
├── create/
└── conditional/
```

---

## 🐛 调试技巧

### VS Code 断点调试

1. 打开 `test_ocr_debug.py`
2. 在第 189 行打断点
3. 按 F5 选择 "Debug OCR Test"
4. 单步执行查看变量

### Print 调试

`agent.py` 已经添加了 print 输出，直接运行即可看到：
- 📄 传递给模型的材料内容
- 📚 旧账摘要
- 🤖 模型返回结果

### 日志文件

在代码中添加：
```python
import logging
logging.basicConfig(filename='debug.log', level=logging.DEBUG)
logging.debug(f"Material: {material_content}")
```

---

## 🎓 核心数据流

```
用户上传文件
    ↓
DocumentParser.parse_file()
    ├─ 普通文件 → 直接提取文字
    └─ 扫描件/图片 → OCR 识别
    ↓
合并文本内容 (workflow._combine_parsed_content)
    ↓
传递给 Agent (agent.process_material)
    ├─ material_content: 文档内容
    └─ ledger_summary: 旧账摘要
    ↓
LangChain 链式调用 (prompt | llm | parser)
    ↓
模型返回 JSON
    ↓
解析为 AgentDecisionBatch
    ↓
程序验证 (validator.validate_decision)
    ↓
冲突解决 (resolve_operation)
    ↓
最终操作 (FinalOperation)
    ↓
输出 3 个 JSON 文件
```

---

## ✅ 项目已完成功能

- ✅ 文件解析（6种格式）
- ✅ LangChain Agent 决策
- ✅ LCEL 链式调用
- ✅ 程序验证保障
- ✅ 冲突智能解决
- ✅ 完整工作流
- ✅ Streamlit 前端
- ✅ 下载功能（已修复）
- ✅ OCR 集成（代码就绪）
- ✅ 调试输出（已添加）

---

## 📞 快速开始

**立即查看效果**：
```bash
# 1. 生成演示报告
python generate_report.py

# 2. 打开浏览器
demo_report.html

# 或者运行应用
streamlit run app.py
```

**测试 Agent 和数据流**：
```bash
python test_ocr_debug.py
```
控制台会显示完整的数据流转过程。

---

## 🎉 总结

项目已 100% 完成，你可以：
1. ✅ 查看演示报告（demo_report.html）
2. ✅ 运行测试脚本查看数据流（test_ocr_debug.py）
3. ✅ 启动应用处理真实文件（streamlit run app.py）
4. ✅ 在控制台看到 OCR 和模型的完整数据

所有调试输出已添加，运行任何脚本都能看到数据流转！
