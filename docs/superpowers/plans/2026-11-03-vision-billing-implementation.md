# 无 OSS 视觉识别与账单自动处理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 无 OSS 处理本地图片和 EML，自动应用已确认的账套规则，并阻止来源金额角色错误进入账本。

**Architecture:** 保留文本提取和事务提交链路。视觉适配器只产生来源文字／表格和识别元数据；策略在匹配后处理缺省值，程序独立核对原文金额角色。并行按文件所有权实现，主线程集成并运行完整离线回归。

**Tech Stack:** Python、requests、Pillow、Poppler、Pydantic、Streamlit、pytest、SQLite；云端视觉使用兼容 chat completions 的 HTTP 协议。

## Global Constraints

- 项目根目录：`D:\桌面\湃乐多笔试题\shipping-billing-agent-v2`；临时目录、日志和缓存都在项目 D 盘。
- 不调用真实付费服务或真实数据库；HTTP／识别服务用替身，数据库用内存 SQLite。
- 不覆盖用户的 `.env`；保留已有业务改动，统一存在冲突的提取口径。
- 不提交 git，不移动或删除 C 盘文件；Python 使用 `-B`，pytest 禁用缓存和插件自动发现。
- 每项行为先写测试，观察预期失败，再实现并运行对应回归。

## Task 1: 视觉适配器和文件解析

**Files:** `src/billing_agent/integrations.py`、`src/billing_agent/parsers.py`、`tests/test_vision_parsing.py`。

**Interfaces:** 新增 `VisionOCRAdapter.is_configured()` 和 `process_local_file(path)`，返回 `text`、`raw`、`provider` 等元数据。`DocumentParser` 新增可注入 `vision_adapter`、`ocr_backend`，显式传旧 OCR 替身时保留旧行为。

- [x] 写 HTTP 请求、图片 Base64、未配置、超时／空响应、扫描页、EML 递归、装饰素材以及同页不重复的失败测试。
- [x] 用 `python -B -m pytest -p no:cacheprovider tests/test_vision_parsing.py -q` 观察缺失功能的失败。
- [x] 实现视觉模式；PDF 临时渲染输出使用 D 盘；旧 remote 模式继续保留。
- [x] 运行新测试和 `tests/test_parsing_pipeline.py`，确认旧 OCR 替身和来源归档不退化。

## Task 2: 主体方向和未映射费用策略

**Files:** `src/billing_agent/models.py`、`src/billing_agent/policies.py`、`src/billing_agent/smart_crud.py`、`tests/test_posting_policy.py`。

**Interfaces:** `SmartCRUDExecutor(..., default_posting_type=None, allow_unmapped_charges=False)`；低层默认保持严格，真实工作流显式传用户业务配置。`FinancialAttributes` 新增方向来源／规则信息；`validate_extracted_charge` 接受 `allow_unmapped_charges=False`。

- [x] 测试新账缺方向按 AR、旧 AP 继承、默认值不伪造方向冲突、真实冲突保留，以及原始未映射费用可警告保存。
- [x] 观察测试失败后，匹配候选再应用策略；保持修订授权、白名单补丁和版本不变。
- [x] 对已解决的方向／映射问题保留记录，再根据剩余问题决定待复核；不忽略其他模型警告。
- [x] 运行新测试及 `tests/test_safe_billing.py`。

## Task 3: 来源金额、提取契约和工作流集成

**Files:** `src/billing_agent/agent.py`、`src/billing_agent/validator.py`、`src/billing_agent/source_amounts.py`、`src/billing_agent/workflow_db.py`、对应新测试。

**Interfaces:** 来源金额观察保留来源块、角色和 Decimal 数值；校验将模型明细和总额分别绑定原文。工作流显式配置识别适配器和主体策略，结构化问题保留严重度与解决状态。

- [x] 写 300／245、错误 total 证据、漏提总额、多个金额列、正确账单及安全提交的回归并观察失败。
- [x] 统一逐费用提取提示词，移除无依据的币种默认；非批准模型映射在宽松模式只保留建议和警告。
- [x] 实现原文总额候选／金额角色检查；校验结果提供数值差额，提交再次核对。
- [x] 为缺失身份字段实现一次带原文证据的定向补提取，不能重写金额／币种或循环重试。
- [x] 集成问题分级、默认 AR 和处理签名；保持来源和版本的幂等保护。

## Task 4: 界面与配置交付

**Files:** `app.py`、`.env.example`、`README.md`、`docs/ocr_setup.md`、`docs/视觉API配置.md`、`tests/test_app_contract.py`。

- [x] 界面测试先覆盖识别配置状态和 description/message/error 兼容展示。
- [x] 显示视觉后端、缺省方向和提示／阻塞区别；识别失败提示重试／配置，不误报金额核对通过。
- [x] 模板使用空密钥和说明，实际 `.env` 保持原样；写清用户申请和填写的视觉地址／模型／密钥、旧 remote 模式及 D 盘输出。
- [x] 运行 AppTest 和完整 `tests` 离线回归；补充验收记录并更新本计划勾选状态。
