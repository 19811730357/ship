"""Streamlit UI for evidence-based billing previews and validated commits."""

import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import date, datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from billing_agent.runtime import OUTPUT_DIR, ROOT_DIR, TEMP_DIR, configure_runtime, configure_streamlit_storage

configure_runtime()

import streamlit as st
configure_streamlit_storage()

from dotenv import load_dotenv

from billing_agent.agent import is_api_configured
from billing_agent.demo import DEMO_SCENARIOS
from billing_agent.workflow import BillingWorkflow
from billing_agent.workflow_db import DatabaseWorkflow

load_dotenv(ROOT_DIR / ".env")


def decimal_default(obj):
    """Keep exact monetary values at the JSON boundary."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def safe_json_dumps(obj, **kwargs):
    return json.dumps(obj, default=decimal_default, **kwargs)


def context_fingerprint(accounting_entity, mode, use_database, db_type, db_config):
    config_names = (
        "QWEN_MODEL", "QWEN_BASE_URL", "OCR_BACKEND", "VISION_MODEL", "VISION_BASE_URL",
        "VISION_CONNECT_TIMEOUT", "VISION_TIMEOUT", "PDFTOPPM_PATH", "OCR_URL", "OCR_TOKEN_HEADER",
        "OCR_CONNECT_TIMEOUT", "OCR_TIMEOUT", "OSS_ENDPOINT", "OSS_BUCKET", "OSS_CREDENTIALS_FILE",
        "DEFAULT_POSTING_TYPE", "ALLOW_UNMAPPED_CHARGES",
    )
    effective_config = {name: os.getenv(name, "").strip() for name in config_names}
    credential_digests = {name: hashlib.sha256(os.getenv(name, "").encode("utf-8")).hexdigest()
                          for name in ("DASHSCOPE_API_KEY", "VISION_API_KEY", "OCR_TOKEN",
                                       "OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET")}
    if effective_config["OSS_CREDENTIALS_FILE"]:
        try:
            path = Path(effective_config["OSS_CREDENTIALS_FILE"])
            credential_digests["OSS_CREDENTIALS_FILE"] = (hashlib.sha256(path.read_bytes()).hexdigest()
                if path.stat().st_size <= 65536 else "invalid-size")
        except OSError:
            credential_digests["OSS_CREDENTIALS_FILE"] = "unreadable"
    context = [accounting_entity, mode, bool(use_database), db_type, db_config,
               effective_config, credential_digests]
    return hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def safe_upload_name(filename, index):
    name = Path(str(filename).replace("\\", "/")).name
    if name in {"", ".", ".."}:
        raise ValueError("上传文件名称无效")
    return f"{index:03d}-{name}"


def issue_message(issue):
    if not isinstance(issue, dict):
        return str(issue)
    return str(next((issue[key] for key in ("message", "error", "description", "reason") if issue.get(key)),
                    "未提供具体说明，请查看运行报告。"))


def issue_is_resolved(issue):
    return isinstance(issue, dict) and bool(
        issue.get("acknowledged") or issue.get("resolved") or issue.get("resolved_by_policy")
        or issue.get("status") in {"resolved", "resolved_by_policy", "resolved_by_reextraction",
                                  "acknowledged", "excluded"})


def issue_is_blocking(issue):
    if not isinstance(issue, dict):
        return True
    return (not issue_is_resolved(issue) and issue.get("blocking") is not False
            and str(issue.get("severity", "error")).lower() not in {"warning", "info"})


def recognition_settings(environ=None):
    """Return public configuration state, never credential values."""
    values = os.environ if environ is None else environ
    backend = str(values.get("OCR_BACKEND", "remote")).strip().lower()
    if backend == "vision":
        missing = []
        if not (str(values.get("VISION_BASE_URL", "")).strip()
                or str(values.get("QWEN_BASE_URL", "")).strip()):
            missing.append("VISION_BASE_URL（或 QWEN_BASE_URL）")
        if not str(values.get("VISION_MODEL", "")).strip():
            missing.append("VISION_MODEL")
        if not (str(values.get("VISION_API_KEY", "")).strip()
                or str(values.get("DASHSCOPE_API_KEY", "")).strip()):
            missing.append("VISION_API_KEY（或 DASHSCOPE_API_KEY）")
        return {"backend": backend, "label": "云端视觉识别（无需 OSS）", "requires_oss": False,
                "configured": not missing, "missing": missing, "requires_file_url": False,
                "local_files_ready": not missing}
    if backend == "remote":
        from src.billing_agent.integrations import OSSAdapter
        missing = [] if str(values.get("OCR_URL", "")).strip() else ["OCR_URL"]
        storage = OSSAdapter(environ=values)
        local_upload_configured = storage.is_configured()
        return {"backend": backend, "label": "公司 OCR（文件 URL 输入）", "requires_oss": False,
                "configured": not missing, "missing": missing, "requires_file_url": True,
                "local_files_ready": not missing and local_upload_configured}
    return {"backend": backend, "label": "未支持的识别后端", "requires_oss": False,
            "configured": False, "missing": ["OCR_BACKEND（remote 或 vision）"],
            "requires_file_url": False, "local_files_ready": False}


def result_state(result):
    report = result.get("run_report", {})
    if report.get("processing_status") == "PROCESSING_FAILED":
        return "partial" if result.get("committed") else "failed"
    pending = result.get("summary", {}).get("operations", {}).get("PENDING_REVIEW", 0)
    active_errors = [issue for issue in report.get("file_errors", []) if issue_is_blocking(issue)]
    if report.get("processing_status") == "COMMITTED" and result.get("committed") and not pending and not active_errors:
        return "committed"
    failed = report.get("files_failed", 0) or active_errors
    if failed and not result.get("processing_results"):
        return "failed"
    if result.get("committed"):
        return "partial" if pending or failed else "committed"
    if result.get("preview_only") or (result.get("preview_only") is None and result.get("preview_id")):
        return "preview"
    if pending:
        return "pending"
    return "completed"


def clear_preview():
    old_workflow = st.session_state.pop("billing_workflow", None)
    close = getattr(old_workflow, "close", None)
    if callable(close):
        close()
    st.session_state.pop("billing_result", None)
    for key in list(st.session_state):
        if str(key).startswith("review_") or str(key).startswith("commit_"):
            del st.session_state[key]


def database_settings():
    backend = os.getenv("DB_TYPE", "sqlite").lower()
    if backend not in {"sqlite", "mysql"}:
        raise ValueError("当前支持 SQLite 和 MySQL，请将 DB_TYPE 设置为 sqlite 或 mysql")
    if backend == "mysql":
        config = {
            "host": os.getenv("DB_HOST", "localhost"), "port": int(os.getenv("DB_PORT", "3306")),
            "user": os.getenv("DB_USER", "root"), "password": os.getenv("DB_PASSWORD", ""),
            "database": os.getenv("DB_NAME", "ship"),
        }
    else:
        db_path = Path(os.getenv("DB_DATABASE", str(OUTPUT_DIR / "billing.db")))
        if not db_path.is_absolute():
            db_path = ROOT_DIR / db_path
        if db_path.drive.upper() != ROOT_DIR.drive.upper():
            raise ValueError("SQLite 数据库必须放在项目所在的 D 盘")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        config = {"database": str(db_path)}
    return backend, config


def get_workflow(accounting_entity, mode, use_database, db_type, db_config):
    if "billing_workflow" not in st.session_state:
        if mode == "真实文件处理" and use_database:
            workflow = DatabaseWorkflow(accounting_entity=accounting_entity, use_mock_data=False,
                                        db_type=db_type, db_config=db_config)
        else:
            workflow = BillingWorkflow(accounting_entity=accounting_entity, use_mock_data=(mode == "模拟演示"))
        st.session_state["billing_workflow"] = workflow
    return st.session_state["billing_workflow"]


def render_issue(issue, prefix=None):
    """Keep actionable details while separating warnings and resolved issues."""
    data = issue if isinstance(issue, dict) else {}
    source_name = prefix or data.get("file") or data.get("source_file") or data.get("filename")
    message = issue_message(issue)
    text = f"{source_name}：{message}" if source_name else message
    if data.get("acknowledged"):
        note = data.get("review_note", data.get("human_note", ""))
        st.caption(f"来源问题已人工确认与本次费用无关：{source_name or '来源材料'}。依据：{note}")
    elif issue_is_resolved(issue):
        st.caption(f"已解决：{text}")
    elif not issue_is_blocking(issue):
        show = st.info if str(data.get("severity", "")).lower() == "info" else st.warning
        show(f"提示：{text}")
    elif data.get("category") in {"business", "validation"}:
        st.warning(f"待复核：{text}")
    else:
        recognition = (data.get("origin") == "parser"
                       or data.get("category") in {"recognition", "configuration", "system"}
                       or str(data.get("code", "")).startswith(("VISION_", "OCR_")))
        st.error(f"{'识别／配置问题' if recognition else '处理问题'}：{text}")


def render_source_documents(result):
    with st.expander("原始材料与解析证据", expanded=False):
        sources = result.get("source_documents", [])
        if not sources:
            st.caption("本次结果没有附带原文块，请在每条费用下查看证据。")
        for source in sources:
            st.write(source.get("source_file", source.get("file_name", source.get("source_id", "材料"))))
            if source.get("source_id"):
                st.caption(f"来源 ID：{source['source_id']}")
            blocks = source.get("blocks", [])
            if blocks:
                for block in blocks:
                    location = block.get("location") or f"页 {block.get('page', '?')} / 行 {block.get('row', '?')}"
                    st.caption(f"{block.get('block_id', '')} · {location}")
                    st.text(block.get("text", ""))
            elif source.get("content"):
                st.text(source["content"])
            for issue in source.get("errors", []):
                render_issue(issue, source.get("source_file"))


def candidate_label(candidate):
    charge = candidate.get("charge_details", {})
    doc = candidate.get("document_info", {})
    return (f"{candidate.get('record_id', '?')} · {doc.get('document_number') or '无单据号'} · "
            f"{charge.get('original_name', '?')} · {charge.get('amount', '?')} {charge.get('currency', '')}")


def render_results(result):
    state = result_state(result)
    messages = {
        "failed": (st.error, "本次识别或提取未完成，请查看具体原因并重试。"),
        "preview": (st.info, "预览已生成，账本尚未写入。核对变更和待复核项后提交。"),
        "committed": (st.success, "已通过校验的变更已提交。"),
        "partial": (st.warning, "已提交通过校验的变更；仍有待复核或失败项，请继续处理。"),
        "pending": (st.warning, "本次未提交费用变更，仍有待复核项。"),
        "completed": (st.info, "处理已结束，请核对下面的操作状态。"),
    }
    show, message = messages[state]
    show(message)
    operations = result.get("summary", {}).get("operations", {})
    for column, name in zip(st.columns(4), ("CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW")):
        column.metric(name, operations.get(name, 0))
    report = result.get("run_report", {})
    for error in report.get("file_errors", []):
        render_issue(error)
    for issue in report.get("warnings", []):
        render_issue({**issue, "severity": "warning"} if isinstance(issue, dict)
                     else {"message": str(issue), "severity": "warning"})
    if report.get("files_skipped"):
        st.caption(f"本次跳过已处理文件 {report['files_skipped']} 个。")
    if report.get("excluded_items"):
        with st.expander("未入账的汇总、条件收费和其他排除项", expanded=False):
            for excluded in report["excluded_items"]:
                st.write(excluded.get("description", "排除项"))
                st.write(excluded.get("reasoning", ""))
                for evidence in excluded.get("evidence", []):
                    st.caption(evidence.get("source_file", ""))
                    st.text(evidence.get("original_text", ""))
    render_source_documents(result)
    items = result.get("processing_results", [])
    if not items:
        st.warning("本次没有可展示的费用结果；这不代表账单金额为零。")
    for index, item in enumerate(items):
        charge = item.get("charge_details", {})
        with st.expander(f"费用 {index + 1}：{charge.get('original_name') or '未识别费用'} · {item.get('operation', 'UNKNOWN')}",
                         expanded=(index == 0 or item.get("operation") == "PENDING_REVIEW")):
            st.write(f"金额：{charge.get('amount', '未知')} {charge.get('currency') or '币种未知'}")
            st.write(f"单据号：{item.get('document_info', {}).get('document_number') or '未知'}")
            financial = item.get("financial_attributes", {})
            if financial.get("posting_type"):
                origins = {"default": "按主体缺省规则", "inherited": "继承匹配旧账", "explicit": "原文明示",
                           "inferred": "模型判断", "model": "模型判断", "model_inferred": "模型推断",
                           "human": "人工核对"}
                origin = origins.get(financial.get("posting_type_origin"), "提取结果")
                st.caption(f"交易方向：{financial['posting_type']} · {origin}")
            st.write(item.get("reason", ""))
            if item.get("validation_issues"):
                st.warning(safe_json_dumps(item["validation_issues"], ensure_ascii=False))
            for warning in item.get("warnings", []):
                render_issue({**warning, "severity": "warning"} if isinstance(warning, dict)
                             else {"message": str(warning), "severity": "warning"})
            for resolved in item.get("resolved_issues", []):
                render_issue({**resolved, "status": "resolved"} if isinstance(resolved, dict)
                             else {"message": str(resolved), "status": "resolved"})
            if item.get("patch"):
                st.write("拟修改字段")
                st.table([{"字段": field, "旧值": str(change.get("old")), "新值": str(change.get("new"))}
                          for field, change in item["patch"].items() if isinstance(change, dict)])
            for evidence in item.get("evidence", []):
                st.caption(f"{evidence.get('source_file', '')} · {evidence.get('location') or evidence.get('block_id') or '位置未提供'}")
                st.text(evidence.get("original_text", ""))
            if item.get("candidates"):
                st.write("候选旧账")
                for candidate in item["candidates"]:
                    st.write(candidate_label(candidate))
                    st.json(candidate)
    stats = result.get("database_stats")
    if stats:
        st.caption(f"当前账本记录：{stats.get('total_records', 0)}；单据：{stats.get('unique_documents', 0)}")
    st.caption(f"解析文件：{report.get('files_succeeded', 0)}；失败：{report.get('files_failed', 0)}；待复核不等于已记账。")


def render_commit_form(result, workflow):
    pending = result.get("summary", {}).get("operations", {}).get("PENDING_REVIEW", 0)
    source_issues = result.get("run_report", {}).get("file_errors", [])
    reviewable_sources = any(isinstance(issue, dict) and issue.get("reviewable") and issue_is_blocking(issue)
                             for issue in source_issues)
    if not result.get("preview_id") or (result.get("committed") and not pending and not reviewable_sources):
        return
    preview_id = str(result["preview_id"])
    actions = {}
    source_reviews = []
    with st.form(f"commit_form_{preview_id}"):
        st.write("提交与人工复核")
        for issue_index, issue in enumerate(source_issues):
            if not isinstance(issue, dict) or not issue.get("reviewable") or not issue_is_blocking(issue):
                continue
            source_name = issue.get("file", issue.get("source_file", issue.get("attachment", "来源材料")))
            st.write(f"来源问题：{source_name} · {issue_message(issue)}")
            exclude = st.checkbox("已核对，与本次费用无关", key=f"review_source_exclude_{preview_id}_{issue_index}")
            note = st.text_area("说明与费用无关的依据", key=f"review_source_note_{preview_id}_{issue_index}",
                                help="仅可排除已核对的无关附件或素材；无法确认时不要勾选。金额、模型提取和单据合计错误仍须解决。")
            if exclude:
                source_reviews.append({"issue_index": issue_index, "note": note.strip(), "exclude": True})
        for index, item in enumerate(result.get("processing_results", [])):
            if item.get("operation") != "PENDING_REVIEW":
                continue
            item_id = str(item.get("item_id", index))
            charge, doc = item.get("charge_details", {}), item.get("document_info", {})
            candidates = item.get("candidates", [])
            by_id = {str(candidate["record_id"]): candidate for candidate in candidates}
            def label(value):
                if value == "keep_pending":
                    return "保留待复核"
                if value == "create":
                    return "人工确认这是新增费用"
                return candidate_label(by_id[value])
            st.write(f"费用 {index + 1}：{charge.get('original_name', '未识别费用')}")
            selection = st.selectbox("关联旧账或确认新增", ["keep_pending", "create"] + list(by_id),
                                     format_func=label, key=f"review_target_{preview_id}_{item_id}")
            values = {}
            fields = [
                ("amount", "核对后的金额", str(charge.get("amount", "") if charge.get("amount") is not None else "")),
                ("currency", "核对后的币种", charge.get("currency") or ""),
                ("issuer", "核对后的签发方", item.get("transaction_party", {}).get("issuer") or ""),
                ("document_number", "核对后的单据号", doc.get("document_number") or ""),
                ("standardized_name", "核对后的标准费用代码", charge.get("standardized_name") or ""),
            ]
            for field, field_label, default in fields:
                values[field] = st.text_input(field_label, value=default, key=f"review_{field}_{preview_id}_{item_id}").strip()
            direction = item.get("financial_attributes", {}).get("posting_type")
            posting_type = st.selectbox("核对后的应收／应付", ["未知", "AR", "AP"],
                                        index={"AR": 1, "AP": 2}.get(direction, 0), key=f"review_posting_{preview_id}_{item_id}")
            note = st.text_area("人工复核依据", key=f"review_note_{preview_id}_{item_id}",
                                help="说明费用身份、金额、币种及交易方向的依据；仍不明确时保留待复核。")
            if selection != "keep_pending":
                actions[item_id] = {
                    "record_id": selection if selection != "create" else None, "approve_create": selection == "create",
                    **{key: value for key, value in values.items() if value or key in {"amount", "currency"}},
                    **({"posting_type": posting_type} if posting_type != "未知" else {}), "note": note.strip(),
                }
        acknowledge = st.checkbox("我已核对上述变更与来源依据", key=f"commit_ack_{preview_id}")
        submit = st.form_submit_button("提交已通过校验的变更", type="primary")
    if submit:
        if not acknowledge:
            st.warning("请先核对并勾选提交确认。")
            return
        if any(not action["note"] for action in actions.values()):
            st.warning("人工处理的费用需要填写复核依据。")
            return
        if any(not review["note"] for review in source_reviews):
            st.warning("确认来源问题与费用无关时，需要填写人工核对依据。")
            return
        if source_reviews:
            actions["__source_reviews__"] = source_reviews
        try:
            st.session_state["billing_result"] = workflow.commit_preview(preview_id, review_actions=actions or None)
            st.rerun()
        except Exception as exc:
            st.error(f"提交未完成：{exc}。请重新核对当前账本后生成预览。")


def render_downloads(result):
    st.write("下载")
    for column, field, label in zip(st.columns(3), ("processing_results", "ledger_snapshot", "run_report"),
                                    ("下载处理结果", "下载完整账本快照", "下载运行报告")):
        with column:
            if field in result:
                st.download_button(label, safe_json_dumps(result[field], indent=2, ensure_ascii=False),
                                   file_name=f"{field}.json", mime="application/json", key=f"download_{field}")


def main():
    st.set_page_config(page_title="航运智能账单助手 V2", page_icon="🚢", layout="wide")
    st.title("航运智能账单助手 V2")
    st.caption("逐条提取费用，核对旧账与修改依据，校验后提交。")
    accounting_entity = st.sidebar.text_input("记账主体", value="湃乐多国际物流", key="accounting_entity").strip()
    mode = st.sidebar.radio("运行模式", ["模拟演示", "真实文件处理"], key="processing_mode")
    use_database = st.sidebar.checkbox("启用数据库持久化", value=True, key="use_database")
    db_type, db_config = None, None
    if use_database and mode == "真实文件处理":
        try:
            db_type, db_config = database_settings()
            st.sidebar.caption(f"数据库：{db_type} / {db_config['database']}")
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
    fingerprint = context_fingerprint(accounting_entity, mode, use_database, db_type, db_config)
    if st.session_state.get("billing_context") != fingerprint:
        clear_preview()
        st.session_state["billing_context"] = fingerprint
    if not accounting_entity:
        st.warning("请先填写记账主体。")
        st.stop()
    if mode == "模拟演示":
        st.info("演示使用固定材料与模型结果，通过同一校验和提交流程处理，不调用外部服务。")
        for scenario_key, info in DEMO_SCENARIOS.items():
            st.write(info["name"])
            st.caption(info["description"])
            if st.button("运行此场景", key=f"btn_{scenario_key}"):
                try:
                    workflow = get_workflow(accounting_entity, mode, False, None, None)
                    st.session_state["billing_result"] = workflow.process_demo_scenario(scenario_key, OUTPUT_DIR / "demo" / scenario_key)
                except Exception as exc:
                    st.error(f"演示失败：{exc}")
    else:
        api_configured = is_api_configured()
        st.sidebar.caption("文本模型密钥：已设置" if api_configured else "文本模型密钥：未设置")
        recognition = recognition_settings()
        st.sidebar.caption(f"图片识别：{recognition['label']}")
        st.sidebar.caption("识别接口：已设置（尚未验证调用）" if recognition["configured"] else "识别接口：待填写")
        if recognition["requires_file_url"]:
            st.sidebar.caption("本地文件 URL 通道：已配置" if recognition["local_files_ready"] else "本地文件 URL 通道：待确认")
        default_direction = os.getenv("DEFAULT_POSTING_TYPE", "AR").strip().upper()
        st.sidebar.caption(f"缺省交易方向：{default_direction or '未启用'}（新账缺少方向时适用）")
        mapping_required = os.getenv("ALLOW_UNMAPPED_CHARGES", "true").strip().lower() in {"0", "false", "no", "off"}
        st.sidebar.caption("未映射费用：需确认标准代码" if mapping_required else "未映射费用：保留原名并提示")
        st.info("上传 EML、PDF、Excel/CSV、DOCX、TXT 或图片。邮件正文和文字 PDF 直接读取；图片及扫描页需满足所选 OCR 接口的输入要求。")
        if recognition["requires_file_url"]:
            st.caption("公司 OCR 的 file 参数是识别服务可读取的文件 URL；识别接口本身不是上传接口。")
            if not recognition["configured"]:
                st.warning("公司 OCR 接口尚未配置：请在项目 .env 中填写 OCR_URL。配置后重启应用；文字材料仍可处理。")
            elif not recognition["local_files_ready"]:
                st.warning("公司 OCR 接口已配置，但本地图片／扫描页仍缺少识别服务可读取的文件 URL。"
                           "目前只有识别请求示例，尚无已确认的上传方式或可用文件 URL；D 盘路径不能代替 URL。"
                           "EML 正文和文字附件仍可读取，图片附件同样受此限制。"
                           "请向题方确认文件上传／存储方式或提供真实可达文件 URL。详见 docs/公司OCR配置与输入限制.md。")
            else:
                st.caption("已配置可选 OSS 上传通道，可用于取得本地文件 URL；连通性和权限仍需另行验证。")
        elif recognition["configured"]:
            st.caption("已显式选择自有云端视觉服务；该可选入口不属于公司 OCR 的必要配置。")
        else:
            st.warning("图片／扫描页识别尚未配置：请在项目 .env 中填写 " + "、".join(recognition["missing"])
                       + "。这是显式选择的可选后端；题方 OCR 主流程使用 OCR_BACKEND=remote。配置后重启应用。")
        uploaded_files = st.file_uploader("材料文件", type=["eml", "pdf", "xlsx", "xls", "csv", "docx", "txt", "png", "jpg", "jpeg"], accept_multiple_files=True)
        ledger_file = st.file_uploader("导入完整旧账快照（可选）", type=["json"])
        force_reprocess = st.checkbox("重新解析已处理文件", value=False, help="重新解析不会授权重复记账或覆盖旧账。")
        allow_updates = st.checkbox("允许根据明确修订依据提出自动更新", value=False,
                                    help="仍须唯一匹配、证据及金额校验通过；有歧义的费用保留待复核。")
        st.caption("每次处理先生成预览，点击提交后才应用已通过校验的变更。")
        if st.button("生成处理预览", type="primary", disabled=not uploaded_files or not api_configured):
            try:
                ledger_data = json.loads(ledger_file.getvalue().decode("utf-8-sig")) if ledger_file else None
                workflow = get_workflow(accounting_entity, mode, use_database, db_type, db_config)
                with st.spinner("解析材料并生成变更方案..."):
                    with TemporaryDirectory(prefix="billing-upload-", dir=TEMP_DIR) as staging:
                        paths = []
                        for index, uploaded in enumerate(uploaded_files, 1):
                            path = Path(staging) / safe_upload_name(uploaded.name, index)
                            path.write_bytes(uploaded.getbuffer())
                            paths.append(path)
                        result = workflow.process_real_files(file_paths=paths, ledger_data=ledger_data,
                            output_dir=OUTPUT_DIR / "runs" / uuid.uuid4().hex,
                            force_reprocess=force_reprocess, preview_only=True, allow_updates=allow_updates)
                st.session_state["billing_result"] = result
            except Exception as exc:
                st.session_state.pop("billing_result", None)
                # 显示详细错误信息
                import traceback
                error_detail = traceback.format_exc()
                st.error(f"处理失败：{exc}")
                with st.expander("查看详细错误信息"):
                    st.code(error_detail)
                # 同时打印到终端
                print("=" * 60)
                print("处理失败 - 详细错误信息：")
                print(error_detail)
                print("=" * 60)
        if not api_configured:
            st.warning("真实提取需要在项目 .env 中配置模型密钥；当前仍可运行离线演示。")
    result = st.session_state.get("billing_result")
    if result is not None:
        render_results(result)
        render_commit_form(result, st.session_state["billing_workflow"])
        render_downloads(result)


if __name__ == "__main__":
    main()
