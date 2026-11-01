# API配置指南

## 快速开始

### 1. 复制配置模板

```bash
cp .env.example .env
```

### 2. 编辑配置文件

使用文本编辑器打开 `.env` 文件：

```bash
# Windows
notepad .env

# Linux/Mac
nano .env
```

### 3. 填写API密钥

最少需要配置千问API密钥：

```bash
DASHSCOPE_API_KEY=sk-your-actual-api-key-here
```

---

## 千问API配置（必需）

### 获取API密钥

1. 访问阿里云DashScope控制台：https://dashscope.console.aliyun.com/
2. 登录或注册账号
3. 进入"API-KEY管理"
4. 创建新的API密钥
5. 复制密钥（以`sk-`开头）

### 配置项说明

```bash
# API密钥（必需）
DASHSCOPE_API_KEY=sk-your-actual-api-key-here

# 模型名称（可选，默认qwen-max）
QWEN_MODEL=qwen-max

# API基础URL（可选，使用默认值即可）
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 可用模型

- `qwen-max` - 最强能力，推荐用于生产环境
- `qwen-plus` - 平衡性能和成本
- `qwen-turbo` - 快速响应，成本较低

### 费用说明

千问API按tokens计费：
- **qwen-max**: 约 0.12元/1K tokens (输入) + 0.12元/1K tokens (输出)
- **qwen-plus**: 约 0.04元/1K tokens (输入) + 0.04元/1K tokens (输出)

单次处理预估：
- 简单场景：约500-1000 tokens，费用 < 0.1元
- 复杂场景：约2000-3000 tokens，费用约 0.2-0.5元

---

## OCR服务配置（可选）

用于识别PDF和图片中的文字。

```bash
# OCR服务地址（题目提供）
OCR_URL=https://gateway.pltplt.com/ai/process

# 认证令牌（如果需要）
OCR_TOKEN=

# 超时设置（秒）
OCR_TIMEOUT=300
OCR_CONNECT_TIMEOUT=10
```

### 使用说明

1. **已提供可下载的PDF/图片URL**：
   - 可以直接使用，不需要OSS上传
   - 在界面中提供文件URL即可

2. **本地PDF/图片文件**：
   - 需要先上传到OSS获得下载URL
   - 或配置OCR服务支持本地文件

---

## OSS配置（可选）

用于上传本地PDF/图片文件，生成OCR可访问的URL。

```bash
OSS_ACCESS_KEY_ID=your-access-key-id
OSS_ACCESS_KEY_SECRET=your-access-key-secret
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET=your-bucket-name
```

### 配置步骤

1. **创建OSS Bucket**：
   - 登录阿里云OSS控制台
   - 创建新的Bucket（建议私有读写）
   - 记录Endpoint和Bucket名称

2. **创建RAM用户**：
   - 进入RAM控制台
   - 创建新用户，勾选"编程访问"
   - 记录AccessKeyID和AccessKeySecret

3. **授权OSS权限**：
   - 为RAM用户添加`AliyunOSSFullAccess`权限
   - 或创建自定义策略，仅授权指定Bucket的读写权限

### 安全建议

- ✅ 使用RAM用户，不要使用主账号密钥
- ✅ 最小权限原则，只授权必要的OSS操作
- ✅ 定期轮换密钥
- ✅ 不要将密钥提交到Git仓库

---

## LibreOffice配置（可选）

用于转换旧版.doc文件。

```bash
SOFFICE_PATH=C:/Program Files/LibreOffice/program/soffice.exe
```

### 安装LibreOffice

1. 下载：https://www.libreoffice.org/download/download/
2. 安装到默认路径
3. 配置路径（Windows示例）：
   ```
   SOFFICE_PATH=C:/Program Files/LibreOffice/program/soffice.exe
   ```

---

## 调试选项

```bash
# 是否启用调试模式
DEBUG=false

# 是否使用模拟数据（不调用真实API）
USE_MOCK_DATA=true

# 日志级别
LOG_LEVEL=INFO
```

### 使用建议

**首次使用**：
```bash
USE_MOCK_DATA=true  # 先用模拟数据熟悉功能
```

**配置完成后**：
```bash
USE_MOCK_DATA=false  # 使用真实API
DEBUG=false
LOG_LEVEL=INFO
```

**遇到问题时**：
```bash
DEBUG=true
LOG_LEVEL=DEBUG  # 查看详细日志
```

---

## 验证配置

### 方法1：启动应用检查

```bash
streamlit run app.py
```

在侧边栏查看"API状态"：
- ✅ 绿色：API已配置
- ⚠️ 黄色：API未配置

### 方法2：运行测试

```python
from src.billing_agent.agent import is_api_configured

if is_api_configured():
    print("✅ API配置正确")
else:
    print("❌ API未配置或密钥无效")
```

---

## 常见问题

### Q1: 提示"API密钥无效"

**原因**：
- 密钥输入错误
- 密钥已过期或被删除
- 密钥权限不足

**解决**：
1. 检查`.env`中的密钥格式（应以`sk-`开头）
2. 在DashScope控制台确认密钥有效
3. 确保没有多余的空格或换行

### Q2: OCR调用失败

**原因**：
- OCR服务地址错误
- 文件URL无法访问
- 超时设置太短

**解决**：
1. 确认`OCR_URL`正确
2. 测试文件URL是否可以直接下载
3. 适当增加`OCR_TIMEOUT`

### Q3: OSS上传失败

**原因**：
- 密钥配置错误
- RAM用户权限不足
- Endpoint或Bucket名称错误

**解决**：
1. 使用OSS控制台测试上传
2. 检查RAM用户权限
3. 确认Endpoint格式（不包含http://前缀）

### Q4: 模型响应很慢

**原因**：
- 网络延迟
- 模型负载高
- 请求内容过多

**解决**：
1. 尝试更换模型（如qwen-turbo）
2. 减少输入材料长度
3. 检查网络连接

---

## 最佳实践

### 1. 密钥管理

- ✅ 使用独立的测试和生产密钥
- ✅ 定期轮换密钥
- ✅ 不要在代码或日志中输出密钥
- ✅ 使用环境变量而不是硬编码

### 2. 成本控制

- ✅ 使用模拟模式测试功能
- ✅ 选择合适的模型（不一定用最贵的）
- ✅ 控制输入材料长度
- ✅ 设置合理的超时时间

### 3. 错误处理

- ✅ 配置DEBUG模式查看详细错误
- ✅ 保存失败的请求日志
- ✅ 实现重试机制（适合临时故障）
- ✅ 对接监控告警

### 4. 安全性

- ✅ .env文件不要提交到Git
- ✅ 生产环境使用加密的配置管理
- ✅ API密钥权限最小化
- ✅ 定期审计密钥使用

---

## 配置示例

### 仅使用模拟数据（推荐首次使用）

```bash
DASHSCOPE_API_KEY=YOUR_API_KEY_HERE
USE_MOCK_DATA=true
DEBUG=false
```

### 完整配置（生产环境）

```bash
# 千问API
DASHSCOPE_API_KEY=sk-actual-key-here
QWEN_MODEL=qwen-max
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# OCR服务
OCR_URL=https://gateway.pltplt.com/ai/process
OCR_TOKEN=
OCR_TIMEOUT=300

# OSS配置
OSS_ACCESS_KEY_ID=LTAI...
OSS_ACCESS_KEY_SECRET=secret...
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET=billing-files

# 运行选项
DEBUG=false
USE_MOCK_DATA=false
LOG_LEVEL=INFO
```

---

## 支持

遇到配置问题：
1. 查看应用日志
2. 检查API服务状态
3. 参考官方文档
4. 提交Issue反馈
