# 图片、PDF 与 EML：使用公司 OCR

项目按题目要求默认使用公司提供的 OCR 接口，不要求另行申请视觉模型或安装本地模型。

```ini
OCR_BACKEND=remote
OCR_URL=https://gateway.pltplt.com/ai/process
OCR_CONNECT_TIMEOUT=10
OCR_TIMEOUT=300
OCR_TOKEN=
```

完整说明见 [公司 OCR 配置与输入限制](公司OCR配置与输入限制.md)。实际 `.env` 中原有文本模型与数据库配置继续保留，修改后重启应用。

## 必须区分接口与文件输入

题目示例通过 POST JSON 发送 `file`（文件 URL）、`task=orderChange`、`callBack`、`taskType`。`OCR_URL` 是处理接口地址，不能同时作为待识别文件地址。

- 已有识别服务器可读取的真实图片／PDF URL：现有 `parse_file_from_url()` 可直接调用，无需 OSS。
- 本地上传图片／扫描附件：需要可达 URL 或公司支持的上传协议；当前代码可选 OSS 桥接已有实现。
- 公司仅给调用示例、没有上传方式时：程序明确记录 `OCR_FILE_URL_REQUIRED`，保留来源文件。不能据此断言公司要求 OSS，也不能擅自假设支持 Base64、multipart 或本地路径。

## EML 和其他文字材料

EML 正文、文字 PDF、Excel、Word 等由本地解析器读取；图片及扫描 PDF 附件进入公司 OCR 路线。附件错误和父子来源关系分别保留，不以正文成功掩盖图片附件失败。

## 可选后端

此前实现的视觉适配器保留供明确选择时使用，不属于题目必须配置，也不是解决公司输入协议缺失的前提。默认配置、界面说明和主处理流程均采用 `remote`。

原文件与解析观察保存在项目 D 盘 `output/sources/`；日志和临时目录也在 D 盘。配置存在不等于真实接口联通，离线测试不等于图片端到端识别通过。
