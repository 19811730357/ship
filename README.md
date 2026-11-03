# 航运账单助手 V2

将邮件和账单材料中的逐条费用提取为结构化数据，检索旧账候选，展示拟修改字段，并在校验通过后提交。默认先生成预览；待复核项不作为正式账本费用写入。

## 处理流程

```text
文件解析与来源归档
  → 模型提取费用、编号、金额角色和字段证据
  → 按记账主体、单据及费用身份检索旧账候选
  → 必要时结合候选提出修订建议
  → 程序校验与字段补丁合并
  → 预览 / 人工复核
  → 事务内提交账本、审计和来源状态
```

演示与真实处理使用同一套业务判断和提交规则。演示使用固定材料和模型结果，不调用外部模型、OCR 或 MySQL；关闭持久化时使用内存账本。

## 本地安装与启动

项目与虚拟环境、依赖缓存、临时文件均应放在 D 盘。已有合适的 Python 环境时可以复用；新环境示例：

```powershell
Set-Location 'D:\桌面\湃乐多笔试题\shipping-billing-agent-v2'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_CACHE_DIR = "$PWD\output\cache\pip"
$env:TEMP = "$PWD\output\temp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP,$env:PIP_CACHE_DIR | Out-Null
python -m venv .venv
.\.venv\Scripts\python.exe -B -m pip install -r requirements.txt
```

使用项目启动入口，先配置 D 盘目录及 Streamlit 存储，再启动界面：

```powershell
.\.venv\Scripts\python.exe -B -c "from src.billing_agent.runtime import launch_streamlit; raise SystemExit(launch_streamlit())"
```

`runtime.py` 将可配置临时目录和缓存定位到项目的 `output/`，日志位于 `logs/`。请从项目目录启动。环境变量配置从项目 `.env` 读取；不要提交真实凭据。

真实模型使用 OpenAI 兼容接口，配置项包括 `DASHSCOPE_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL`。密钥存在仅表示已设置，不代表服务已联通。

图片和扫描 PDF 默认使用题方提供的公司 OCR：`OCR_BACKEND=remote`、`OCR_URL=https://gateway.pltplt.com/ai/process`。不需要另行申请视觉模型。示例的 `file` 是 OCR 服务可读取的文件 URL；它没有说明本地文件如何上传。接口地址配置齐全不等于本地图片输入通道已就绪，详见 [公司 OCR 配置与输入限制](docs/公司OCR配置与输入限制.md)。实际 `.env` 保留在本地，配置模板只提供空密钥。

当前样例已完成 OSS 上传和公司 OCR 真实联调；EML 正文与两个原生文字 PDF 附件可读，已核验的推广图按精确摘要排除。接口未返回的币种保持未知并人工核对，详见 [真实联调记录](docs/verification-2026-11-03-live-ocr.md)。更新配置后停止并重新启动应用，再生成新预览。

V4 已修复界面上传中文文件名时公司 OCR 返回空结果的兼容问题：云端使用内部 ASCII 文件名，来源保留原名。已按界面文件名真实验证，详见 [图片上传修复记录](docs/verification-2026-11-03-image-filename-fix.md)。

## 使用方式

1. 填写记账主体。不同主体的数据与文件处理状态分别检索。
2. 先运行模拟演示了解预览和复核；真实处理时上传材料，可选导入完整旧账快照。
3. 点击“生成处理预览”。需要模型读取材料；费用尚未提交到正式账本。
4. 核对每条费用的原文、来源位置、候选旧账、修改前后字段和失败原因。
5. 有歧义的费用选择正确候选或明确确认新增，必要时补正金额、币种、签发方、单据号、费用代码和 AR/AP，并填写人工依据。无法确认的项目保留待复核。
6. 点击“提交已通过校验的变更”。程序重新验证候选及版本；合计冲突等硬性错误不能仅凭人工说明绕过。
7. 下载处理结果、完整账本快照和运行报告。部分成功时继续处理待复核项，已提交项不会重复执行。

页面刷新及下载不会再次调用提取。更换主体、运行模式或数据库配置会清除当前预览，防止把旧方案提交到另一账套。预览保存在当前会话，关闭会话后需重新生成。

“允许根据明确修订依据提出自动更新”只允许程序在费用身份唯一、字段证据和修订依据充分时生成更新方案；仍需通过校验并在界面提交。金额不同本身不构成修改依据。

`DEFAULT_POSTING_TYPE=AR` 用于新账缺少方向时的业务兜底；已匹配旧账优先继承旧方向，原文明示与旧账冲突仍需复核。`ALLOW_UNMAPPED_CHARGES=true` 允许保留未映射费用原名并显示提示，设为 `false` 可要求标准费用代码。界面区分提示、已解决问题、识别／配置失败与业务待复核，不因缺省规则已解决的字段反复要求人工。

## 数据库与历史数据

支持 SQLite 与 MySQL，暂不提供 PostgreSQL 实现。

- SQLite 默认位置为项目 `output/billing.db`；可用 `DB_DATABASE` 指定其他 D 盘路径。
- MySQL 使用 `DB_TYPE=mysql`、`DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD`、`DB_NAME`，驱动为 PyMySQL。
- 新表使用 `billing_` 前缀：单据、费用明细、类型化编号、变更历史和来源状态分别保存。
- 旧 `ledger_records` 等表保留，不自动把旧整单总额拆成费用明细。旧记录作为历史汇总处理，需要核对原始材料后再迁移。
- 首次接入旧 SQLite 文件时在 `output/backups/` 留存备份。接入 MySQL 前请将数据库备份导出到 D 盘；应用不会自动执行服务器级备份。

每条新费用以固定记录 ID 标识；同名费用可有多条。MBL、HBL、订舱号、箱号分别保存，多个箱号不会将整单费用重复记账。数值计算使用 Decimal；内部 JSON 金额使用十进制字符串，SQLite 存为精确文本，MySQL 使用定点数。

原始单据金额、当前费用金额和审计历史分别保留。字段补丁不会用新材料中的缺失值清空旧账。提交同时检查旧记录版本，过期预览需要重新生成。

## 文件与 OCR

支持 EML、文本 PDF、Excel/XLS/CSV、DOCX、TXT 和常见图片。旧版 DOC 不在界面支持范围。

- EML 优先读取纯文本正文，否则读取清理后的 HTML；递归解析附件，保留父子来源关系、附件失败信息及大小/层数限制。
- 文本与表格尽量保留页、行或单元格位置；无法取得的坐标保持未知。
- 默认 `OCR_BACKEND=remote` 调用题方 OCR，按示例传入 `file`、`task`、`callBack`、`taskType`，无需视觉模型配置；文字 PDF 继续原生读取。
- 远端 OCR 接收可达 URL。本地文件需要额外的上传／链接获取方式；当前可选 OSS 桥接已实现，但它不是题目接口的强制要求。没有输入通道时明确报告 `OCR_FILE_URL_REQUIRED`，保留原文件，不伪报识别成功。
- 原视觉适配器只作为显式选择的可选实现保留，不属于题目要求，默认配置和流程不会要求申请视觉 API。
- OCR 返回空文本、服务失败或附件解析失败会明确报错，不能以占位文本冒充成功。
- 旧 remote 后端创建的云端临时对象使用唯一名称；成功完成后清理。请求超时不能证明服务已停止读取，对象会保留待清理状态；请根据报告核对后处理。已有用户 URL 对象不由本系统删除。
- 原文件与解析来源归档在 `output/sources/`。清理上传暂存目录不会删除归档。
- 每个来源页面使用一份正式识别结果，重试观察独立保存。只有明确无关的签名／Logo 才可排除并记录依据，疑似账单图片失败不能静默忽略。

真实处理会将选定材料发送至配置的模型服务；视觉模式直接发送图片，旧 remote 模式还涉及所配置的 OCR 和对象存储。离线演示和默认测试不发送材料。

## 测试与验收

默认测试仅收集 `tests/`。根目录历史 `test_*.py` 包含真实数据库写入及付费模型调用，不属于默认测试集合，不要批量执行它们。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider
```

离线测试使用固定模型返回、内存或 D 盘临时 SQLite、视觉 HTTP／OCR／OSS 替身，覆盖主体隔离、同名费用歧义、明确修订、字段保留、版本冲突、事务回滚、文件重处理、快照往返以及 UI 预览生命周期。

离线通过不代表真实模型、OCR 或 MySQL 已验收。真实联调应使用独立测试库和固定样例，分别核对解析文本、逐字段提取、操作类型、旧账 ID、修改后金额、未改字段和审计记录。不能只以“调用成功”或“有 UPDATE 数量”判断正确。

## 模块

| 文件 | 职责 |
|---|---|
| `app.py` | 预览、复核、提交及下载，会话内保留工作流 |
| `runtime.py` | D 盘运行目录和可配置缓存 |
| `parsers.py` / `integrations.py` | 解析、来源定位、云端视觉及可选 OCR／对象存储适配 |
| `agent.py` | 结构化提取及受候选范围约束的修订建议 |
| `models.py` | 单据、费用、字段证据及输出数据契约 |
| `smart_crud.py` / `validator.py` | 候选身份、变更方案及硬规则校验 |
| `ledger.py` | 补丁合并及快照导入导出 |
| `database.py` | 作用域检索、版本检查、事务和历史数据兼容 |
| `workflow.py` / `workflow_db.py` | 统一编排与持久化接入 |

`docs/` 中原有交付文档属于历史记录，其中“100% 完成”“所有生产问题已解决”等表述不作为本版本验收结论。当前行为以源码、此 README 和实际测试记录为准。
