"""
Streamlit Web应用
航运智能账单助手界面
"""

import streamlit as st
import json
from pathlib import Path
import sys
import os
from dotenv import load_dotenv
from decimal import Decimal
from datetime import datetime, date

# 加载环境变量
load_dotenv()

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from billing_agent.workflow import BillingWorkflow
from billing_agent.demo import DEMO_SCENARIOS, get_demo_ledger
from billing_agent.agent import is_api_configured


# ============================================
# JSON 序列化辅助函数
# ============================================

def decimal_default(obj):
    """处理 Decimal 和 datetime 类型的 JSON 序列化"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def safe_json_dumps(obj, **kwargs):
    """安全的 JSON 序列化，处理 Decimal 和 datetime 类型"""
    return json.dumps(obj, default=decimal_default, **kwargs)


# ============================================
# 页面配置
# ============================================

st.set_page_config(
    page_title="航运智能账单助手 V2",
    page_icon="🚢",
    layout="wide"
)

st.title("🚢 航运智能账单助手 V2")
st.markdown("**基于大模型决策的智能账单处理系统**")

# ============================================
# 侧边栏配置
# ============================================

st.sidebar.header("⚙️ 配置")

# 记账主体
accounting_entity = st.sidebar.text_input(
    "记账主体",
    value="Demo Origin",
    help="当前的记账主体名称"
)

# 运行模式
mode = st.sidebar.radio(
    "运行模式",
    ["模拟演示", "真实文件处理"],
    help="模拟模式使用预设场景，不调用API"
)

use_mock_data = (mode == "模拟演示")

# API配置状态
st.sidebar.markdown("---")
st.sidebar.subheader("📡 API状态")

api_configured = is_api_configured()
if api_configured:
    st.sidebar.success("✅ 千问API已配置")
else:
    st.sidebar.warning("⚠️ 千问API未配置")
    st.sidebar.info("使用模拟模式或在.env中配置DASHSCOPE_API_KEY")


# ============================================
# 主界面
# ============================================

if mode == "模拟演示":
    st.header("📋 模拟演示模式")

    st.info("""
    **演示模式说明**：使用预设场景展示系统功能，不调用真实API。

    **核心特性展示**：
    - ✨ 模型给出操作建议（CREATE/UPDATE/NO_CHANGE）
    - 🔍 程序独立验证决策
    - ⚖️ 模型与程序冲突时智能解决
    - 📊 完整的决策过程追踪
    """)

    # 场景选择
    st.subheader("选择演示场景")

    scenario_cols = st.columns(2)

    for i, (scenario_key, scenario_info) in enumerate(DEMO_SCENARIOS.items()):
        col = scenario_cols[i % 2]

        with col:
            st.markdown(f"**{scenario_info['name']}**")
            st.caption(scenario_info['description'])

            if st.button(f"运行此场景", key=f"btn_{scenario_key}"):
                st.session_state['selected_scenario'] = scenario_key

    # 运行场景
    if 'selected_scenario' in st.session_state:
        scenario_key = st.session_state['selected_scenario']
        scenario_info = DEMO_SCENARIOS[scenario_key]

        st.markdown("---")
        st.subheader(f"🎬 运行场景：{scenario_info['name']}")

        with st.spinner("处理中..."):
            try:
                # 创建工作流
                workflow = BillingWorkflow(
                    accounting_entity=accounting_entity,
                    use_mock_data=True
                )

                # 处理场景
                output_dir = Path("output") / scenario_key
                results = workflow.process_demo_scenario(scenario_key, output_dir)

                # 显示结果
                st.success("✅ 处理完成！")

                # 显示摘要
                col1, col2, col3, col4 = st.columns(4)

                summary = results['summary']
                col1.metric("CREATE", summary['operations']['CREATE'])
                col2.metric("UPDATE", summary['operations']['UPDATE'])
                col3.metric("NO_CHANGE", summary['operations']['NO_CHANGE'])
                col4.metric("PENDING_REVIEW", summary['operations']['PENDING_REVIEW'])

                # 显示详细结果
                st.subheader("📊 处理结果详情")

                for i, result in enumerate(results['processing_results']):
                    with st.expander(
                        f"费用 #{i+1}: {result['charge_details']['original_name']} - {result['operation']}",
                        expanded=(i == 0)
                    ):
                        # 操作类型
                        op_type = result['operation']
                        if op_type == "CREATE":
                            st.success(f"✨ **操作**: {op_type}")
                        elif op_type == "UPDATE":
                            st.info(f"🔄 **操作**: {op_type}")
                        elif op_type == "NO_CHANGE":
                            st.info(f"➡️ **操作**: {op_type}")
                        else:
                            st.warning(f"⚠️ **操作**: {op_type}")

                        # 决策过程
                        st.markdown("##### 🤖 模型决策")
                        st.write(f"- **建议操作**: {result['model_suggestion']}")
                        st.write(f"- **置信度**: {result['model_confidence']}")
                        st.write(f"- **理由**: {result['model_reasoning']}")

                        st.markdown("##### 🔍 程序验证")
                        st.write(f"- **程序判断**: {result['program_validation']}")
                        if result['validation_issues']:
                            st.write(f"- **验证问题**: {', '.join(result['validation_issues'])}")
                        else:
                            st.write("- **验证问题**: 无")

                        if result['conflict_resolution']:
                            st.markdown("##### ⚖️ 冲突解决")
                            st.write(result['conflict_resolution'])

                        # 费用详情
                        st.markdown("##### 💰 费用详情")
                        charge = result['charge_details']
                        st.write(f"- **金额**: {charge['amount']} {charge['currency']}")
                        st.write(f"- **付款方式**: {charge.get('payment_method', 'N/A')}")

                        # 单据信息
                        doc = result['document_info']
                        if doc.get('document_number'):
                            st.markdown("##### 📄 单据信息")
                            st.write(f"- **单据号**: {doc['document_number']}")
                            if doc.get('bill_of_lading'):
                                st.write(f"- **提单号**: {doc['bill_of_lading']}")

                # 排除项
                if summary['excluded_items'] > 0:
                    st.subheader("🚫 排除项")
                    st.info(f"共 {summary['excluded_items']} 项被排除（如条件条款、汇总行等）")

                # 下载按钮
                st.subheader("📥 下载结果")

                col1, col2, col3 = st.columns(3)

                with col1:
                    st.download_button(
                        label="下载处理结果",
                        data=safe_json_dumps(results['processing_results'], indent=2, ensure_ascii=False),
                        file_name="processing_results.json",
                        mime="application/json"
                    )

                with col2:
                    st.download_button(
                        label="下载账本快照",
                        data=safe_json_dumps(results['ledger_snapshot'], indent=2, ensure_ascii=False),
                        file_name="ledger_snapshot.json",
                        mime="application/json"
                    )

                with col3:
                    st.download_button(
                        label="下载运行报告",
                        data=safe_json_dumps(results['run_report'], indent=2, ensure_ascii=False),
                        file_name="run_report.json",
                        mime="application/json"
                    )

            except Exception as e:
                st.error(f"处理失败: {str(e)}")
                st.exception(e)

else:
    # 真实文件处理模式
    st.header("📁 真实文件处理")

    if not api_configured:
        st.error("""
        ❌ **真实文件处理需要配置API密钥**

        请按以下步骤操作：
        1. 复制 `.env.example` 为 `.env`
        2. 在 `.env` 中填写 `DASHSCOPE_API_KEY`
        3. 重启应用
        """)
        st.stop()

    st.info("""
    **支持的文件格式**：
    - 📧 EML邮件文件
    - 📄 PDF文档
    - 📊 Excel表格（.xlsx, .xls, .csv）
    - 📝 Word文档（.docx）
    - 📃 纯文本（.txt）
    - 🖼️ 图片（.png, .jpg等，需OCR）
    """)

    # 文件上传区域
    st.subheader("1️⃣ 上传材料文件")

    uploaded_files = st.file_uploader(
        "选择要处理的文件",
        type=['eml', 'pdf', 'xlsx', 'xls', 'csv', 'docx', 'txt', 'png', 'jpg', 'jpeg'],
        accept_multiple_files=True,
        help="可以同时上传多个文件，系统会合并处理"
    )

    # 旧账导入
    st.subheader("2️⃣ 导入旧账（可选）")

    col1, col2 = st.columns([3, 1])

    with col1:
        ledger_file = st.file_uploader(
            "上传旧账JSON文件",
            type=['json'],
            help="如果有旧账数据，上传JSON格式的账本文件"
        )

    with col2:
        use_empty_ledger = st.checkbox("使用空账本", value=True, help="不导入旧账，从空账本开始")

    # 处理按钮
    st.subheader("3️⃣ 开始处理")

    # 使用 session_state 追踪处理次数
    if 'process_count' not in st.session_state:
        st.session_state.process_count = 0

    if st.button("🚀 开始处理", type="primary", disabled=not uploaded_files, key=f"process_btn_{st.session_state.process_count}"):
        if not uploaded_files:
            st.warning("请先上传至少一个文件")
        else:
            # 增加处理计数
            st.session_state.process_count += 1

            with st.spinner("正在处理文件..."):
                try:
                    # 保存上传的文件到临时目录
                    import tempfile
                    temp_dir = Path(tempfile.mkdtemp())
                    file_paths = []

                    for uploaded_file in uploaded_files:
                        file_path = temp_dir / uploaded_file.name
                        with open(file_path, 'wb') as f:
                            f.write(uploaded_file.getbuffer())
                        file_paths.append(file_path)

                    st.info(f"已上传 {len(file_paths)} 个文件")

                    # 加载旧账
                    ledger_data = None
                    if ledger_file and not use_empty_ledger:
                        ledger_data = json.loads(ledger_file.read().decode('utf-8'))
                        st.info("已加载旧账数据")
                    else:
                        st.info("使用空账本")

                    # 创建工作流
                    workflow = BillingWorkflow(
                        accounting_entity=accounting_entity,
                        use_mock_data=False
                    )

                    # 处理文件
                    output_dir = Path("output") / f"real_processing_{st.session_state.process_count}"
                    results = workflow.process_real_files(
                        file_paths=file_paths,
                        ledger_data=ledger_data,
                        output_dir=output_dir
                    )

                    # 显示结果
                    st.success("✅ 处理完成！")

                    # 显示摘要
                    st.subheader("📊 处理摘要")
                    col1, col2, col3, col4 = st.columns(4)

                    summary = results['summary']
                    col1.metric("CREATE", summary['operations']['CREATE'])
                    col2.metric("UPDATE", summary['operations']['UPDATE'])
                    col3.metric("NO_CHANGE", summary['operations']['NO_CHANGE'])
                    col4.metric("PENDING_REVIEW", summary['operations']['PENDING_REVIEW'])

                    # 显示详细结果
                    st.subheader("📋 处理结果详情")

                    for i, result in enumerate(results['processing_results']):
                        with st.expander(
                            f"费用 #{i+1}: {result['charge_details']['original_name']} - {result['operation']}",
                            expanded=(i == 0)
                        ):
                            # 操作类型
                            op_type = result['operation']
                            if op_type == "CREATE":
                                st.success(f"✨ **操作**: {op_type}")
                            elif op_type == "UPDATE":
                                st.info(f"🔄 **操作**: {op_type}")
                            elif op_type == "NO_CHANGE":
                                st.info(f"➡️ **操作**: {op_type}")
                            else:
                                st.warning(f"⚠️ **操作**: {op_type}")

                            # 决策过程
                            st.markdown("##### 🤖 模型决策")
                            st.write(f"- **建议操作**: {result['model_suggestion']}")
                            st.write(f"- **置信度**: {result['model_confidence']}")
                            st.write(f"- **理由**: {result['model_reasoning']}")

                            st.markdown("##### 🔍 程序验证")
                            st.write(f"- **程序判断**: {result['program_validation']}")
                            if result['validation_issues']:
                                st.write(f"- **验证问题**: {', '.join(result['validation_issues'])}")
                            else:
                                st.write("- **验证问题**: 无")

                            if result['conflict_resolution']:
                                st.markdown("##### ⚖️ 冲突解决")
                                st.write(result['conflict_resolution'])

                            # 费用详情
                            st.markdown("##### 💰 费用详情")
                            charge = result['charge_details']
                            st.write(f"- **金额**: {charge['amount']} {charge['currency']}")
                            st.write(f"- **付款方式**: {charge.get('payment_method', 'N/A')}")

                            # 单据信息
                            doc = result['document_info']
                            if doc.get('document_number'):
                                st.markdown("##### 📄 单据信息")
                                st.write(f"- **单据号**: {doc['document_number']}")
                                if doc.get('bill_of_lading'):
                                    st.write(f"- **提单号**: {doc['bill_of_lading']}")

                    # 排除项
                    if summary['excluded_items'] > 0:
                        st.subheader("🚫 排除项")
                        st.info(f"共 {summary['excluded_items']} 项被排除（如条件条款、汇总行等）")

                    # 运行报告
                    st.subheader("📈 运行报告")
                    report = results['run_report']

                    col1, col2, col3 = st.columns(3)
                    col1.metric("文件总数", report['files_processed'])
                    col2.metric("成功", report['files_succeeded'])
                    col3.metric("失败", report['files_failed'])

                    if report['file_errors']:
                        st.error("文件处理错误:")
                        for err in report['file_errors']:
                            st.write(f"- {err['file']}: {err['error']}")

                    # 下载按钮
                    st.subheader("📥 下载结果")

                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.download_button(
                            label="下载处理结果",
                            data=safe_json_dumps(results['processing_results'], indent=2, ensure_ascii=False),
                            file_name="processing_results.json",
                            mime="application/json"
                        )

                    with col2:
                        st.download_button(
                            label="下载账本快照",
                            data=safe_json_dumps(results['ledger_snapshot'], indent=2, ensure_ascii=False),
                            file_name="ledger_snapshot.json",
                            mime="application/json"
                        )

                    with col3:
                        st.download_button(
                            label="下载运行报告",
                            data=safe_json_dumps(results['run_report'], indent=2, ensure_ascii=False),
                            file_name="run_report.json",
                            mime="application/json"
                        )

                    # 清理临时文件
                    import shutil
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass

                except Exception as e:
                    st.error(f"❌ 处理失败: {str(e)}")
                    st.exception(e)


# ============================================
# 页脚
# ============================================

st.sidebar.markdown("---")
st.sidebar.markdown("""
### 📚 关于本系统

**版本**: 2.0.0

**核心特点**:
- 模型主导决策
- 程序验证保障
- 冲突智能解决
- 完整审计追踪

**文档**: 查看 `docs/` 目录

**技术栈**: LangChain, Pydantic, Streamlit
""")
