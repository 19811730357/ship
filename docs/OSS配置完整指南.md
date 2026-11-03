# 🔧 OSS 配置完整指南

## 📋 你的 OSS 信息

| 配置项 | 值 |
|--------|-----|
| **Bucket 名称** | `ocr-phy` |
| **地域** | 上海 |
| **Endpoint** | `oss-cn-shanghai.aliyuncs.com` |
| **AccessKey ID** | 待配置 |
| **AccessKey Secret** | 待配置 |

---

## 🚀 快速配置步骤

### 步骤1：获取 AccessKey

1. 登录[阿里云控制台](https://ram.console.aliyun.com/manage/ak)
2. 点击"创建 AccessKey"
3. **立即复制**并保存：
   - `AccessKey ID`（示例：LTAI5tXXXXXXXXXXXXXX）
   - `AccessKey Secret`（示例：XXXXXXXXXXXXXXXXXXXXXXXX）
   
   ⚠️ **重要**：Secret 只显示一次，务必立即保存！

---

### 步骤2：配置环境变量

**方法A：创建 .env 文件（推荐）**

1. 复制 `.env.example` 为 `.env`：
   ```bash
   copy .env.example .env
   ```

2. 编辑 `.env` 文件，填入你的 AccessKey：
   ```bash
   # 阿里云 OSS 配置
   OSS_BUCKET=ocr-phy
   OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com
   OSS_ACCESS_KEY_ID=LTAI5tXXXXXXXXXXXXXX    # 替换为你的
   OSS_ACCESS_KEY_SECRET=XXXXXXXXXXXXXXXX    # 替换为你的
   ```

3. 保存文件

**方法B：系统环境变量**

Windows PowerShell：
```powershell
$env:OSS_BUCKET="ocr-phy"
$env:OSS_ENDPOINT="oss-cn-shanghai.aliyuncs.com"
$env:OSS_ACCESS_KEY_ID="你的AccessKey ID"
$env:OSS_ACCESS_KEY_SECRET="你的AccessKey Secret"
```

---

### 步骤3：设置 Bucket 权限

1. 进入[OSS控制台](https://oss.console.aliyun.com/)
2. 找到 `ocr-phy` Bucket
3. 点击"权限管理" → "读写权限"
4. 设置为：**私有**（推荐）或 **公共读**

**推荐设置：私有 + 签名URL**
- 更安全
- 系统会自动生成临时访问URL

---

### 步骤4：验证配置

创建测试脚本 `test_oss.py`：

```python
from src.billing_agent.integrations import OSSAdapter

# 测试配置
oss = OSSAdapter()

if oss.is_configured():
    print("✅ OSS 配置成功！")
    print(f"   Bucket: {oss.bucket_name}")
    print(f"   Endpoint: {oss.endpoint}")
else:
    print("❌ OSS 未配置")
    print("请检查环境变量：")
    print("  - OSS_ACCESS_KEY_ID")
    print("  - OSS_ACCESS_KEY_SECRET")
    print("  - OSS_ENDPOINT")
    print("  - OSS_BUCKET")
```

运行测试：
```bash
python test_oss.py
```

---

### 步骤5：重启应用

```bash
streamlit run app.py
```

现在可以处理图片文件了！ 🎉

---

## 🧪 测试 OSS 功能

### 测试1：上传图片文件

1. 准备一张账单图片（JPG/PNG）
2. 在 Streamlit 界面上传
3. 查看处理结果

**预期结果**：
- ✅ 图片被识别
- ✅ 提取文字内容
- ✅ 提取费用信息
- ✅ 保存到数据库

### 测试2：上传 EML（带图片附件）

1. 准备一封包含图片附件的邮件
2. 保存为 .eml 格式
3. 上传处理

**预期结果**：
- ✅ 邮件正文解析
- ✅ PDF 附件解析
- ✅ 图片附件识别
- ✅ 所有内容整合

---

## ⚠️ 常见问题

### Q1: 提示 "OSS未配置"

**原因**：环境变量未生效

**解决**：
1. 检查 `.env` 文件是否存在
2. 检查文件名是否正确（不是 `.env.txt`）
3. 重启 Streamlit
4. 检查变量名拼写

### Q2: 上传失败 "NoSuchBucket"

**原因**：Bucket 名称或 Endpoint 错误

**解决**：
1. 确认 Bucket 名称：`ocr-phy`
2. 确认 Endpoint：`oss-cn-shanghai.aliyuncs.com`
3. 确认 Bucket 在上海区域

### Q3: 上传失败 "AccessDenied"

**原因**：AccessKey 无权限

**解决**：
1. 检查 AccessKey 是否正确
2. 确认 RAM 用户有 OSS 权限
3. 建议使用主账号 AccessKey（测试）

### Q4: 图片识别失败

**原因**：可能是 OCR 服务未配置

**说明**：
- OSS 只负责存储图片
- OCR 负责识别文字
- 需要同时配置 `OCR_URL` 和 `OCR_TOKEN`

---

## 🔒 安全建议

### 1. 不要提交 .env 到 Git

`.gitignore` 中已包含：
```
.env
.env.local
```

### 2. 使用 RAM 子账号

不要使用主账号 AccessKey，创建 RAM 子账号：

1. 进入 [RAM 控制台](https://ram.console.aliyun.com/)
2. 创建用户
3. 只授予 OSS 权限
4. 生成 AccessKey

### 3. 定期轮换密钥

建议每3-6个月更换一次 AccessKey

### 4. 设置 Bucket 生命周期

自动删除旧文件，节省费用：

1. 进入 Bucket 管理
2. "基础设置" → "生命周期"
3. 添加规则：30天后删除

---

## 💰 费用说明

### OSS 收费项

| 项目 | 说明 | 估算 |
|------|------|------|
| **存储费用** | 按存储量计费 | 约 ¥0.12/GB/月 |
| **流量费用** | 上传免费，下载计费 | 约 ¥0.5/GB |
| **请求费用** | PUT/GET 请求次数 | 约 ¥0.01/万次 |

### 成本控制

1. **及时清理**：处理完的图片可以删除
2. **设置配额**：限制最大存储量
3. **监控费用**：定期查看账单

**估算**：每月处理1000张图片
- 存储：1000 * 2MB = 2GB → ¥0.24
- 请求：1000次上传 + 1000次下载 → ¥0.02
- 流量：2GB下载 → ¥1.00
- **总计：约 ¥1.26/月**

---

## 📞 获取帮助

### 遇到问题？

1. 查看日志：命令行窗口的输出
2. 检查配置：运行 `test_oss.py`
3. 查看文档：`docs/OSS配置说明.md`

### 常用链接

- [OSS 控制台](https://oss.console.aliyun.com/)
- [RAM 控制台](https://ram.console.aliyun.com/)
- [OSS 文档](https://help.aliyun.com/product/31815.html)

---

## ✅ 配置检查清单

配置完成后，确认：

- [ ] 已获取 AccessKey ID 和 Secret
- [ ] 已创建 `.env` 文件
- [ ] 已填入正确的配置信息
- [ ] Bucket 名称：`ocr-phy`
- [ ] Endpoint：`oss-cn-shanghai.aliyuncs.com`
- [ ] 运行 `test_oss.py` 显示 ✅
- [ ] 重启 Streamlit
- [ ] 上传图片测试成功

---

**配置完成后，就可以处理图片和 EML 中的图片附件了！** 🎉

---

## 🎯 下一步

配置好 OSS 后：

1. **测试图片识别**
   - 上传一张清晰的账单图片
   - 观察是否正确识别

2. **测试 EML 处理**
   - 上传包含附件的邮件
   - 确认所有附件都被处理

3. **调整 OCR 配置**（如果需要）
   - 配置 `OCR_URL`
   - 配置 `OCR_TOKEN`

4. **优化 Prompt**
   - 根据识别结果调整
   - 提高提取准确率

---

**有问题随时问我！** 🚀
