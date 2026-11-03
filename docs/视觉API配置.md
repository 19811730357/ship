# 云端视觉 API 配置

> 本文仅说明保留的可选视觉后端。按用户最新要求，题目主流程默认使用公司提供的 `OCR_URL`，无需申请视觉模型；请先阅读 [公司 OCR 配置与输入限制](公司OCR配置与输入限制.md)。

本项目保留现有文本模型，并为图片和扫描 PDF 增加独立的云端视觉识别入口。视觉模式将图片编码为 Base64 后直接发送到 API，不需要安装本地视觉模型、模型权重或 GPU，也不需要配置 OSS。它仍需要联网，并会产生所选服务的接口调用费用。

## 1. 申请什么服务

向服务商申请支持图像输入、兼容 `chat/completions` 的视觉模型 API，取得：

| 配置 | 需要填写的内容 |
|---|---|
| `VISION_BASE_URL` | API 基础地址，例如服务商提供的兼容接口 `/v1` 地址 |
| `VISION_MODEL` | 账户已开通的视觉模型名称，必须支持图片输入 |
| `VISION_API_KEY` | 此视觉接口的 API Key |

可以使用千问，也可以使用符合相同接口协议的服务。地址、密钥和模型必须属于适用的服务区域与账户；不能仅将文本模型名称换成任意视觉模型名就认为权限已经开通。

千问支持图片 Base64 输入的说明：[视觉理解官方文档](https://help.aliyun.com/en/model-studio/vision)。具体模型、权限、额度和价格以申请时服务商控制台为准。

## 2. 编辑项目 `.env`

配置文件位置：`D:\桌面\湃乐多笔试题\shipping-billing-agent-v2\.env`。

已有 `.env` 时只补充或修改以下配置，不要用模板覆盖现有数据库和文本模型配置：

```ini
# 图片和扫描页直接调用视觉模型，不经过 OSS
OCR_BACKEND=vision
VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_MODEL=填写账号已开通的视觉模型名称
VISION_API_KEY=填写视觉API密钥

# 可选超时（秒）
VISION_CONNECT_TIMEOUT=10
VISION_TIMEOUT=300

# 新账缺少方向时采用 AR；匹配旧账时优先继承旧方向
DEFAULT_POSTING_TYPE=AR
ALLOW_UNMAPPED_CHARGES=true
```

上面地址适用于相应千问兼容服务；其他服务商或区域必须使用其提供的地址。程序接受基础地址，也接受已经以 `/chat/completions` 结尾的完整请求地址。

- `VISION_MODEL` 必须填写，程序不会替你猜测或自动开通模型。
- `VISION_API_KEY` 留空时复用 `DASHSCOPE_API_KEY`；同一千问账户也需要确认视觉模型调用权限。跨服务商不要复用不适用的密钥。
- `VISION_BASE_URL` 留空时复用 `QWEN_BASE_URL`。建议明确填写，避免将图片误发到另一个服务地址。
- 文本模型继续使用 `DASHSCOPE_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`，不需要整体替换。
- 模板 `.env.example` 只包含空密钥。密钥只写本地 `.env`，不要贴到截图或提交到仓库。

若尚无 `.env`，先复制 `.env.example`，再填写文本模型、视觉模型和所需数据库配置。

## 3. 扫描 PDF 的额外工具

图片本身可以直接发送；扫描 PDF 的页面先由 Poppler 的 `pdftoppm` 转成 PNG，再发送。它是 PDF 渲染工具，不是视觉模型。

`pdftoppm` 已在 `PATH` 时不需要配置；否则将工具解压／安装在 D 盘，并设置其可执行文件路径：

```ini
PDFTOPPM_PATH=D:/tools/poppler/Library/bin/pdftoppm.exe
```

按实际安装路径填写，不要直接照抄不存在的目录。扫描页临时图片写入项目 D 盘目录，识别后清理。文字型 PDF 继续读取原生文字，不要求逐页调用视觉模型。

## 4. 重启与检查

修改 `.env` 后停止并重新启动应用。复用已有 Python 环境时，从项目目录执行：

```powershell
Set-Location 'D:\桌面\湃乐多笔试题\shipping-billing-agent-v2'
python -B -c "from src.billing_agent.runtime import launch_streamlit; raise SystemExit(launch_streamlit())"
```

在“真实文件处理”模式检查侧栏：

- 图片识别应显示“云端视觉识别（无需 OSS）”。
- 缺少配置时，页面会列出 `VISION_MODEL`、`VISION_API_KEY` 等具体配置名。
- “已设置”仅表示本地字段齐全，不代表网络、账户权限或接口余额已经验证。

建议先用普通账单图片生成预览，确认有来源文本，再用 EML 和扫描 PDF 测试。生成预览可能调用付费接口；核对后明确提交才写入费用账本。

## 5. EML 如何识别

EML 正文使用邮件解析器读取，不需要 OCR。图片和扫描 PDF 附件进入视觉识别，文字 PDF 附件继续原生解析。邮件、附件和每页识别保留各自来源。

明确判定为无关签名或 Logo 的素材可以排除并记录依据；疑似账单或无法确定的图片不能仅因处于邮件内嵌位置就忽略。识别失败、超时、空内容或超限会明确报告，不以占位文字冒充账单内容。

本地图片识别保护上限为 10 MiB；转换后的图片也检查。多帧图片需要先拆成单帧。大文件请先按页／单张整理，不能将所有页反复缩小到金额无法辨认。

## 6. 原有 OCR／OSS 的保留方式

已有 URL 型 OCR 服务时可继续使用：

```ini
OCR_BACKEND=remote
OCR_URL=填写原有OCR服务地址
OCR_TOKEN=按服务要求填写
OSS_ACCESS_KEY_ID=填写访问密钥ID
OSS_ACCESS_KEY_SECRET=填写访问密钥
OSS_ENDPOINT=填写OSS端点
OSS_BUCKET=填写桶名称
```

只有这个后端的本地文件需要先上传取得可访问 URL。不能把 Base64 直接写入旧服务的 `file` URL 参数并假设它支持。两种识别后端选择其一；无需为视觉模式额外申请 OSS。

## 7. 验收与排查

| 现象 | 核对方式 |
|---|---|
| 仍提示需要 OSS | 检查 `OCR_BACKEND=vision`，并确认已重启应用 |
| 未填写模型或密钥 | 补齐页面列出的配置；方向规则不能解决识别配置缺失 |
| 接口权限／模型不存在 | 检查模型名、区域、账户权限和基础地址是否匹配 |
| 图片可识别，扫描 PDF 失败 | 检查 `pdftoppm` 或 `PDFTOPPM_PATH` |
| 返回空内容／非预期格式 | 检查服务是否支持图像消息及所配置接口协议，查看具体识别问题 |
| 未映射标准费用 | 默认保留原名并提示；严格模式设置 `ALLOW_UNMAPPED_CHARGES=false` |
| 无明确 AR/AP | 新账采用默认 AR，旧账继承已匹配方向；明确冲突仍复核 |
| 明细与总额不同 | 必须核对来源与差额，不能仅依靠换视觉模型解决 |

原文件及解析观察在项目 `output/sources/`，日志在 `logs/`，临时文件和缓存在项目 `output/`。接口密钥及图片 Base64 请求体不应写入日志。

程序回归测试使用视觉接口替身，不验证实际申请的 API。真实联调请先使用独立测试账套；对“明细 300、总额 245”要核对是否分别提取、显示差额 55、保持待复核且不写本单费用，而不能只看接口调用成功。
