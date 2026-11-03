# 公司 OCR 路线修正验收

用户已明确：只有题方提供的 `https://gateway.pltplt.com/ai/process` 请求示例，没有额外视觉模型、上传接口或可访问文件链接。本轮据此修正默认路线，不要求用户申请视觉 API。

## 完成内容

- 工作流及处理签名缺省 `OCR_BACKEND=remote`；接口请求沿用题方 `file/task/callBack/taskType` JSON 格式。
- 界面及模板默认公司 OCR。接口地址是否配置、本地文件 URL 通道是否就绪分别显示；OSS 是已有可选桥接，不称为接口本身强制要求。
- 本地输入缺少桥接时记录 `OCR_FILE_URL_REQUIRED`，保留原件及结构化错误，不再误指向视觉模型配置。
- 已有可访问 URL 时，代码入口可以直接调用公司 OCR，不需要 OSS；没有假定公司支持 Base64／multipart。
- 实际 `.env` 未改。README、OCR 指南及公司配置说明已对齐。旧视觉实现只供显式选择，不作为题目要求。

## 回归

先观察公司默认路线、签名和缺输入元数据的3项预期失败，再修复；界面相关预期失败也先于实现观察。

最终完整离线回归：**253 passed, 1 warning**。警告为既有 PyPDF2 弃用提示。公司 OCR 请求用 HTTP 替身，未调用真实 OCR／模型／OSS 或数据库。

所有本轮测试均设置 `PYTHONDONTWRITEBYTECODE=1`、`-B`、禁用pytest缓存与插件自动发现；TEMP/TMP/TMPDIR指向项目D盘。最终目录 `output/test-temp/company-ocr-final`。

## 尚未完成的真实条件

示例 `file` 是文件 URL，而题方未说明本地文件上传方式。现有资源不足以完成本地图片／扫描附件的真实公司 OCR 闭环；本轮不宣称图片／EML端到端已识别通过。

需要公司补充：可达文件链接或上传接口，或确认支持的文件直传协议，以及实际返回 JSON／鉴权要求。文字邮件正文和文字型 PDF 仍可原生读取。

本轮源码、说明和测试输出均在 D 盘，无 C 盘写入；未清理或修改 C 盘已有文件。
