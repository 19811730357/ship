# 🎯 OSS 配置 - 快速开始

## 📋 你的配置信息

已为你准备好的配置：

```bash
OSS_BUCKET=ocr-phy
OSS_ENDPOINT=oss-cn-shanghai.aliyuncs.com
```

**还需要你填写的**：
- `OSS_ACCESS_KEY_ID` - 从阿里云控制台获取
- `OSS_ACCESS_KEY_SECRET` - 从阿里云控制台获取

---

## 🚀 三步配置

### 第一步：获取 AccessKey

1. 访问：https://ram.console.aliyun.com/manage/ak
2. 点击"创建 AccessKey"
3. **立即复制并保存**（Secret 只显示一次！）

### 第二步：配置环境变量

1. **复制配置文件**：
   ```bash
   copy .env.example .env
   ```

2. **编辑 .env 文件**，找到这几行：
   ```bash
   OSS_ACCESS_KEY_ID=your_access_key_id_here
   OSS_ACCESS_KEY_SECRET=your_access_key_secret_here
   ```

3. **替换为你的 AccessKey**：
   ```bash
   OSS_ACCESS_KEY_ID=LTAI5tXXXXXXXXXXXXXX
   OSS_ACCESS_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXXXX
   ```

4. **保存文件**

### 第三步：验证配置

运行测试脚本：
```bash
python test_oss.py
```

**期望输出**：
```
✅ OSS 配置完整！

【配置详情】
  Bucket 名称: ocr-phy
  地域节点: oss-cn-shanghai.aliyuncs.com
  访问密钥: LTAI5tXXXX...XXXX
```

---

## ✅ 配置完成后

### 重启应用
```bash
streamlit run app.py
```

### 测试图片处理
1. 上传一张账单图片（JPG/PNG）
2. 系统会自动：
   - 上传图片到 OSS
   - 调用 OCR 识别
   - 提取费用信息
   - 保存到数据库

---

## 🎯 配置前 vs 配置后

| 文件类型 | 配置前 | 配置后 |
|---------|--------|--------|
| PDF | ✅ 可以 | ✅ 可以 |
| Excel | ✅ 可以 | ✅ 可以 |
| Word | ✅ 可以 | ✅ 可以 |
| 图片 | ❌ 跳过 | ✅ 可以 |
| EML (带图片) | ⚠️ 部分 | ✅ 全部 |

---

## 📞 需要帮助？

### 问题1：找不到 AccessKey

→ 访问：https://ram.console.aliyun.com/manage/ak

### 问题2：.env 文件不生效

→ 确认文件名是 `.env`，不是 `.env.txt`

### 问题3：配置后还是提示未配置

→ 重启 Streamlit（Ctrl+C 停止，再运行 `streamlit run app.py`）

### 问题4：上传失败

→ 运行 `python test_oss.py` 检查配置

---

## 📚 详细文档

- **完整配置指南**：`docs/OSS配置完整指南.md`
- **常见问题**：`docs/OSS配置说明.md`
- **项目总结**：`docs/项目完成总结.md`

---

**配置好后就可以处理图片了！** 🎉
