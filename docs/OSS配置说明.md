# OSS 配置说明

## 🎯 为什么需要 OSS？

**图片和邮件附件需要通过 OCR 识别文字**，流程如下：

```
图片文件 → 上传到 OSS → 获取 URL → 调用 OCR API → 返回文字
```

**如果不配置 OSS**：
- ✅ 可以处理：PDF、Excel、Word、TXT
- ❌ 无法处理：图片（PNG、JPG等）、EML 邮件中的图片附件

---

## 📝 配置方法

### 方法1：环境变量配置（推荐）

在项目根目录创建 `.env` 文件：

```bash
# 阿里云 OSS 配置
OSS_ACCESS_KEY_ID=your_access_key_id
OSS_ACCESS_KEY_SECRET=your_access_key_secret
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET=your_bucket_name

# OCR 服务配置
OCR_URL=https://your-ocr-service.com/api/ocr
OCR_TOKEN=your_ocr_token
OCR_TOKEN_HEADER=Authorization
OCR_CONNECT_TIMEOUT=10
OCR_TIMEOUT=300
```

### 方法2：系统环境变量

在 Windows 系统环境变量中设置：
1. 打开"系统属性" → "环境变量"
2. 添加用户变量：
   - `OSS_ACCESS_KEY_ID`
   - `OSS_ACCESS_KEY_SECRET`
   - `OSS_ENDPOINT`
   - `OSS_BUCKET`

---

## 🔧 获取 OSS 凭证

### 阿里云 OSS

1. 登录[阿里云控制台](https://oss.console.aliyun.com/)
2. 创建 Bucket（或使用已有的）
3. 获取 AccessKey：
   - 进入"AccessKey 管理"
   - 创建 AccessKey
   - 记录 `AccessKeyId` 和 `AccessKeySecret`
4. 获取 Endpoint：
   - 在 Bucket 列表中查看
   - 例如：`oss-cn-hangzhou.aliyuncs.com`

---

## 🎯 配置检查

### 检查 OSS 是否配置成功

运行以下 Python 代码：

```python
from src.billing_agent.integrations import OSSAdapter

oss = OSSAdapter()
if oss.is_configured():
    print("✅ OSS 配置成功")
else:
    print("❌ OSS 未配置")
```

---

## 💡 替代方案：只处理 PDF 文件

**如果不想配置 OSS**，可以：

1. **只上传 PDF 文件**（不上传图片）
2. **将图片转换为 PDF** 后再上传
3. **使用在线工具**将 JPG/PNG 转为 PDF

**转换工具推荐**：
- Adobe Acrobat
- 在线工具：[ilovepdf.com](https://www.ilovepdf.com/jpg_to_pdf)
- Python 脚本：使用 PIL/Pillow

---

## ⚠️ 注意事项

1. **安全性**：
   - 不要将 `.env` 文件提交到 Git
   - AccessKey 要保密

2. **费用**：
   - OSS 存储和流量会产生费用
   - 建议设置生命周期规则自动删除旧文件

3. **权限**：
   - AccessKey 需要有 OSS 的读写权限
   - 建议使用 RAM 子账号，只授予必要权限

---

## 📞 常见问题

### Q: 我暂时不想配置 OSS，能用吗？

**A**: 可以！只要不上传图片文件即可。PDF、Excel、Word 都可以正常处理。

### Q: 配置后还是提示未配置？

**A**: 检查：
1. 环境变量是否正确设置
2. 重启 Streamlit 应用
3. 检查 `.env` 文件是否在项目根目录

### Q: 上传失败怎么办？

**A**: 检查：
1. AccessKey 是否有效
2. Bucket 是否存在
3. Endpoint 是否正确
4. 网络连接是否正常
