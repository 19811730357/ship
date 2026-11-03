# 公司 OCR 配置与输入限制

> 实测更新：用户已补充并授权上海 `ocr-phy` 桶和新的访问凭据。当前上传通道已配置，示例图片真实识别成功；公司接口返回 `data.list/chargeList`，解析器已适配。下面“缺上传方式”是原始题目示例的限制，不再表示当前项目没有上传配置。

## 当前项目配置与实测结论

```ini
OCR_BACKEND=remote
OCR_URL=https://gateway.pltplt.com/ai/process
OSS_BUCKET=ocr-phy
OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
OSS_CREDENTIALS_FILE=D:/桌面/湃乐多笔试题/shipping-billing-agent-v2/.secrets/oss-credentials.csv
```

完整的环境变量访问凭据优先；两者均未填写时读取指定 CSV，不能混用两份凭据。CSV 支持阿里云导出的 `AccessKey ID,AccessKey Secret` 列，不输出密钥。当前新 OSS 凭据只存放在已忽略的 `.secrets/oss-credentials.csv`；`.env` 中的 OSS 两项密钥留空。现有仓库已经跟踪 `.env`，忽略规则不会使已跟踪文件自动脱离版本控制；不要把真实密钥填入版本文件。更改后必须停止并重新启动应用，再生成新预览。

AccessKey 属于阿里云账号／RAM 用户，不在 Bucket 中单独创建；能否访问取决于授权。本次新凭据已通过实际图片上传、公司 OCR 拉取和临时对象清理，无需把桶改成公共读写。[官方授权说明](https://www.alibabacloud.com/help/en/oss/user-guide/authentication)

真实图片已识别到单号 `ORFR1618731` 及 `5.00`、`21.90` 两项费用。服务没有返回币种，用户已确认保留未知、人工核对，不默认填 USD。

EML 正文和两个 PDF 附件已成功读取。已查看的推广横幅按精确摘要登记在 `config/non_billing_assets.json`，仅在邮件附件范围按核验理由排除；同名但不同内容的图片仍走 OCR，未知图片不能因空响应被自动忽略。

公司响应转换为带来源的字段观察，保留原始 JSON；它不是图片逐字转录，不能把缺失字段当作已识别事实。

## 项目依据

当前题目只提供以下调用协议，用户没有额外视觉模型、上传接口或文件 URL。项目默认依赖公司 OCR，不要求另行申请视觉模型 API，也不要求安装本地视觉模型。

```python
import requests

file_url = "https://your-file-server.example/bill.pdf"  # 必须替换成真实可达文件链接
response = requests.post(
    "https://gateway.pltplt.com/ai/process",
    json={"file": file_url, "task": "orderChange", "callBack": "", "taskType": ""},
    timeout=(10, 300),
)
response.raise_for_status()
ocr_result = response.json()
```

示例中的 `example.com/bill.pdf` 只是占位，不是题目样例文件的实际地址。Python 字符串应为纯 URL，不能包含 Markdown 的 `[地址](地址)` 写法。

## 实际配置

在项目 `.env` 中保留现有文本模型和数据库配置，使用：

```ini
OCR_BACKEND=remote
OCR_URL=https://gateway.pltplt.com/ai/process
OCR_CONNECT_TIMEOUT=10
OCR_TIMEOUT=300
OCR_TOKEN=
```

未设置 `OCR_BACKEND` 时也默认 `remote`。修改代码／配置后重启应用。示例未携带认证，项目不凭空要求视觉 Key；如公司另行说明 Token，按其协议填写 `OCR_TOKEN` 及需要的请求头配置。

界面分别显示：

- **公司 OCR 接口已设置**：仅表示 `OCR_URL` 已填，不代表网络、认证和真实响应通过验证。
- **本地文件 URL 通道待确认**：当前尚不能将电脑上的图片／扫描附件变成 OCR 服务器可访问的链接。

## 当前确实缺少的环节

`file` 是识别服务器能够读取的图片／PDF URL。`D:\桌面\账单.pdf` 不是远端可访问的链接，电脑上的 `localhost` 通常也不是远端服务器可达地址。

已经有文件 URL 时，现有 `DocumentParser.parse_file_from_url()` 可以直接调用公司 OCR，无需 OSS。对本地上传，现有代码仅实现了可选 OSS 上传桥接。题方接口本身不要求 OSS，但也没有在示例里提供其他上传方式。

因此只有这段示例时，**无法确认仅靠一个 OCR_URL 就能上传本地文件**。程序会记录 `OCR_FILE_URL_REQUIRED`，保留原件和错误，不假装识别成功，不把该缺项说成需要视觉模型。

需要公司补充确认的协议是：

1. `file` 是否仅接受 URL，还是支持 Base64／multipart 文件直传；若支持，参数名和请求示例是什么。
2. 如果只接受 URL，是否提供配套文件上传接口或样例文件的可访问链接。
3. 调用是否需要认证，以及成功／失败的实际返回 JSON 结构。

没有这些说明时，不直接把 Base64 塞进 URL 字段，不自行创建公网隧道或假定其他上传地址存在。

## EML 的处理

邮件正文通过本地邮件解析器读取；文字型 PDF 附件可以原生读取。图片和扫描 PDF 附件需要满足公司 OCR 的输入条件，不能因为邮件正文成功就宣称全部附件识别成功。

## 验证边界

离线替身已验证公司接口请求字段、默认后端和已有 URL 无 OSS 调用路径。真实公司 OCR 的网络、权限、实际响应和本地上传闭环仍需要对应输入资源后验收，不能以离线回归替代。

项目源码、解析归档、日志和测试输出位于 D 盘；实际 `.env` 未被本次修正覆盖。
