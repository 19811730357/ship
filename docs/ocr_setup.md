# OCR 配置指南

## OCR 服务说明

系统已集成 OCR（光学字符识别）服务，用于识别：
- 📄 **扫描件 PDF** - PyPDF2 无法提取文字的图片型 PDF
- 🖼️ **图片文件** - PNG/JPG 格式的账单截图

## OCR API 接口

```python
import requests

file_url = "https://example.com/bill.pdf"
url = "https://gateway.pltplt.com/ai/process"

data = {
    "file": file_url,           # 文件URL（必需）
    "task": "orderChange",      # 任务类型
    "callBack": "",             # 回调URL（可选）
    "taskType": ""              # 任务子类型（可选）
}

response = requests.post(url, json=data, timeout=(10, 300))
response.raise_for_status()
ocr_result = response.json()
```

## 配置步骤

### 1. 编辑 `.env` 文件

```bash
# OCR 服务配置
OCR_URL=https://gateway.pltplt.com/ai/process
OCR_TIMEOUT=300
OCR_CONNECT_TIMEOUT=10
```

### 2. 重启应用

```bash
streamlit run app.py
```

### 3. 确认状态

在 Streamlit 界面的侧边栏会显示：
- ✅ OCR已配置
- ⚠️ OCR未配置

## 使用方式

### 方式1：通过前端上传（推荐用于测试）

目前前端上传的文件是**本地文件**，OCR 服务需要**文件 URL**。

**限制**：本地文件无法直接用 OCR，需要先上传到服务器获取 URL。

**提示**：系统会显示"[图片文件检测到，但需要提供文件URL给OCR服务]"

### 方式2：直接提供文件 URL（推荐）

如果你的文件已经上传到服务器，可以使用 `parse_file_from_url()` 方法：

```python
from billing_agent.parsers import DocumentParser
from billing_agent.integrations import OCRAdapter

# 初始化
ocr_adapter = OCRAdapter()
parser = DocumentParser(ocr_enabled=True, ocr_adapter=ocr_adapter)

# 解析URL文件
result = parser.parse_file_from_url(
    file_url="https://example.com/bill.pdf",
    file_type="pdf"
)

print(result['content'])  # OCR识别的文本
```

### 方式3：集成 OSS 上传（完整方案）

如果需要处理用户上传的本地文件，建议配置 OSS：

#### 步骤1：配置 OSS

在 `.env` 中添加：

```bash
# 阿里云 OSS 配置
OSS_ACCESS_KEY_ID=你的AccessKeyId
OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com
OSS_BUCKET=你的bucket名称
```

#### 步骤2：修改 parsers.py

```python
def _ocr_pdf(self, file_path: Path, metadata: dict) -> str:
    if not self.ocr_adapter:
        return "[需要配置OCR服务]"
    
    # 使用 OSS 上传获取 URL
    if self.oss_adapter:
        file_url = self.oss_adapter.upload_and_get_url(str(file_path))
    else:
        return "[需要配置OSS上传服务]"
    
    # 调用 OCR
    ocr_result = self.ocr_adapter.process_file(file_url, task="orderChange")
    
    if ocr_result.get('code') == 0 or ocr_result.get('success'):
        ocr_text = self._extract_ocr_text(ocr_result)
        metadata['ocr_processed'] = True
        return f"[OCR识别结果]\n{ocr_text}"
    else:
        error_msg = ocr_result.get('message', 'Unknown error')
        return f"[OCR识别失败: {error_msg}]"
```

#### 步骤3：更新 workflow.py

```python
from .integrations import OCRAdapter, OSSAdapter

ocr_adapter = OCRAdapter()
oss_adapter = OSSAdapter()
ocr_enabled = ocr_adapter.is_configured() and oss_adapter.is_configured()

parser = DocumentParser(
    ocr_enabled=ocr_enabled,
    oss_adapter=oss_adapter if ocr_enabled else None,
    ocr_adapter=ocr_adapter if ocr_enabled else None
)
```

## OCR 返回格式处理

OCR 服务返回的 JSON 格式可能是：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "text": "识别的文本内容..."
  }
}
```

或者：

```json
{
  "success": true,
  "data": [
    {"text": "第一行内容"},
    {"text": "第二行内容"}
  ]
}
```

系统会自动解析 `_extract_ocr_text()` 方法处理不同格式。

## 当前实现状态

✅ **已实现**：
- OCR API 调用封装（integrations.py）
- OCR 配置检测
- 文件 URL OCR 识别
- OCR 结果解析

⚠️ **需要配置**：
- 本地文件 → URL 的转换（需要 OSS 或文件服务器）
- 前端直接上传到 OSS 的功能

💡 **建议**：
- 对于测试：使用已有的文件 URL 直接调用 OCR
- 对于生产：配置 OSS 实现完整的本地文件 → OCR 流程

## 测试 OCR

创建测试脚本 `test_ocr.py`：

```python
from src.billing_agent.integrations import OCRAdapter

# 初始化
ocr = OCRAdapter()

# 测试OCR（需要一个公网可访问的PDF URL）
file_url = "https://example.com/test.pdf"
result = ocr.process_file(file_url, task="orderChange")

print("OCR结果:")
print(result)
```

运行：

```bash
conda activate ship_env
python test_ocr.py
```

## 常见问题

### Q: 为什么上传本地文件无法使用 OCR？

**A**: OCR 服务需要文件 URL，不能直接处理本地文件。需要先上传到 OSS 或文件服务器。

### Q: 如何配置 OSS？

**A**: 在 `.env` 中填写阿里云 OSS 的 AccessKey、Endpoint 和 Bucket 信息。

### Q: OCR 识别失败怎么办？

**A**: 检查：
1. 文件 URL 是否公网可访问
2. OCR 服务是否正常
3. 查看返回的错误信息

### Q: 可以不用 OSS 吗？

**A**: 可以，但需要自己实现文件上传服务，获取公网 URL 后传给 OCR。

## 架构图

```
本地文件上传
    ↓
[方案1] 直接解析（Word/Excel/有文字的PDF）
    ↓
提取的文本 → LangChain Agent

[方案2] OCR识别（扫描件PDF/图片）
    ↓
上传到OSS获取URL
    ↓
调用OCR API
    ↓
识别的文本 → LangChain Agent
```
