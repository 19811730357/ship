"""
LangChain Agent实现
模型决策型Agent，给出CRUD操作建议
"""

from typing import List, Dict, Any, Optional
import os
import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from .models import (
    AgentDecisionBatch,
    AgentDecision,
    Ledger,
    ChargeDetails,
    DocumentInfo,
    TransactionParty,
    FinancialAttributes,
    Evidence
)


# ============================================
# Agent提示词模板
# ============================================

AGENT_SYSTEM_PROMPT = """你是航运账单智能助手。你的任务是分析材料并提取账单信息。

**重要业务规则**：
1. **识别账单类型**：
   - 如果材料是账单（Invoice/Debit Note），应提取总金额（TOTAL/GRAND TOTAL）
   - 明细项（line items）仅作为参考，不单独记录
   - 一张账单 = 一条记录

2. **提取原则**：
   - 优先查找：TOTAL、GRAND TOTAL、BALANCE DUE、AMOUNT DUE 等总金额字段
   - 明细项存储在 line_items 数组中，用于审计和核对
   - 如果找不到总金额，则计算所有明细项之和

3. **条件收费条款**：
   - "如果...则收取"、"若超期..."等条件性描述排除
   - 仅提取实际已发生的费用

**当前记账主体**：{accounting_entity}

**输出格式**：返回JSON对象，包含decisions数组和excluded_items数组。

**示例**：
材料中有：
```
HANDLING CHARGE        65.00
ADD'L DETENTION     1,310.40
HANDLING CHARGE        45.00
------------------------
TOTAL               1,420.40 USD
```

应该输出：
{{
  "decisions": [{{
    "charge_details": {{
      "original_name": "DEBIT NOTE",
      "amount": 1420.40,
      "currency": "USD",
      "line_items": [
        {{"description": "HANDLING CHARGE", "amount": 65.00, "currency": "USD"}},
        {{"description": "ADD'L DETENTION FREE TIME CHARGE", "amount": 1310.40, "currency": "USD"}},
        {{"description": "HANDLING CHARGE", "amount": 45.00, "currency": "USD"}}
      ]
    }},
    "document_info": {{
      "document_type": "DEBIT_NOTE",
      "document_number": "DC-108478"
    }},
    "transaction_party": {{
      "issuer": "签发方",
      "recipient": "接收方"
    }},
    "financial_attributes": {{
      "posting_type": "AR",
      "posting_type_reasoning": "应收账款"
    }},
    "evidence": [{{
      "source_file": "文件名",
      "source_type": "attachment",
      "original_text": "TOTAL 1,420.40 USD"
    }}]
  }}],
  "excluded_items": []
}}

注意：所有金额字段使用数字类型，不要加引号。
"""


# ============================================

# 用户提示词模板
USER_PROMPT_TEMPLATE = """
**材料内容**：
{material_content}

**旧账记录**：
{ledger_summary}

请严格按照上述JSON格式分析材料并返回结果。
"""


# ============================================
# 辅助函数
# ============================================

def format_ledger_summary(ledger: Ledger) -> str:
    """
    格式化旧账摘要供LLM阅读

    Args:
        ledger: 账本对象

    Returns:
        格式化的文本摘要
    """
    if not ledger.records:
        return "无旧账记录"

    summary_parts = []
    for idx, record in enumerate(ledger.records, 1):
        summary_parts.append(
            f"记录 #{idx}:\n"
            f"  - ID: {record.record_id}\n"
            f"  - 费用名称: {record.charge_details.original_name}\n"
            f"  - 标准名称: {record.charge_details.standardized_name or 'N/A'}\n"
            f"  - 金额: {record.charge_details.amount} {record.charge_details.currency}\n"
            f"  - 付款方式: {record.charge_details.payment_method or 'N/A'}\n"
            f"  - 单据号: {record.document_info.document_number or 'N/A'}\n"
            f"  - 提单号: {record.document_info.bill_of_lading or 'N/A'}\n"
        )

    return "\n".join(summary_parts)


def parse_agent_response(response_dict: Dict[str, Any], accounting_entity: str) -> AgentDecisionBatch:
    """
    解析LLM返回的JSON，转换为AgentDecisionBatch对象

    Args:
        response_dict: LLM返回的字典
        accounting_entity: 记账主体

    Returns:
        AgentDecisionBatch对象
    """
    print(f"\n[Agent Parser] Parsing LLM response...")
    print(f"  Response keys: {list(response_dict.keys())}")
    print(f"  Decisions count: {len(response_dict.get('decisions', []))}")

    decisions = []

    for i, dec_data in enumerate(response_dict.get('decisions', []), 1):
        try:
            print(f"\n  [Decision #{i}]")

            # 确保必需字段存在
            charge_details_data = dec_data.get('charge_details', {})
            print(f"    Charge details keys: {list(charge_details_data.keys())}")

            if not charge_details_data.get('original_name'):
                print(f"    ⚠️  Warning: 跳过缺少费用名称的决策")
                continue
            if not charge_details_data.get('amount'):
                print(f"    ⚠️  Warning: 跳过缺少金额的决策")
                continue

            print(f"    Name: {charge_details_data.get('original_name')}")
            print(f"    Amount: {charge_details_data.get('amount')} {charge_details_data.get('currency')}")

            # 检查 line_items
            if charge_details_data.get('line_items'):
                print(f"    Line items: {len(charge_details_data['line_items'])} items")

            # 确保evidence不为空
            evidence_list = dec_data.get('evidence', [])
            if not evidence_list:
                # 添加默认证据
                evidence_list = [{
                    'source_file': 'uploaded_document',
                    'source_type': 'user_upload',
                    'original_text': charge_details_data.get('original_name', 'N/A')
                }]

            # 确保financial_attributes包含accounting_entity
            financial_attrs = dec_data.get('financial_attributes', {})
            financial_attrs['accounting_entity'] = accounting_entity

            # 构建AgentDecision对象
            # 注意：新 Prompt 不要求 LLM 判断操作类型，这些字段使用默认值
            decision = AgentDecision(
                suggested_operation=dec_data.get('suggested_operation', 'CREATE'),  # 默认 CREATE
                operation_reasoning=dec_data.get('operation_reasoning', 'Extracted from document'),
                matched_record_id=dec_data.get('matched_record_id'),
                confidence=dec_data.get('confidence', 'HIGH'),
                charge_details=ChargeDetails(**charge_details_data),
                document_info=DocumentInfo(**dec_data.get('document_info', {})),
                transaction_party=TransactionParty(**dec_data.get('transaction_party', {})),
                financial_attributes=FinancialAttributes(**financial_attrs),
                evidence=[Evidence(**e) for e in evidence_list],
                field_changes=dec_data.get('field_changes')
            )
            decisions.append(decision)
            print(f"    ✅ Decision parsed successfully")

        except Exception as e:
            # 跳过解析失败的决策
            print(f"    ❌ Error: 跳过一个解析失败的决策: {str(e)}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n[Agent Parser] Total parsed decisions: {len(decisions)}")

    # 解析excluded_items，容错处理
    excluded_items = []
    for exc_data in response_dict.get('excluded_items', []):
        try:
            # 确保必需字段，提供默认值
            if not exc_data.get('item_type'):
                exc_data['item_type'] = 'other'
            if not exc_data.get('description'):
                exc_data['description'] = 'Excluded item'
            if not exc_data.get('reasoning'):
                exc_data['reasoning'] = 'Not specified'

            # 确保evidence字段
            if 'evidence' not in exc_data:
                exc_data['evidence'] = []

            from .models import ExcludedItem
            excluded_item = ExcludedItem(**exc_data)
            excluded_items.append(excluded_item)
        except Exception as e:
            print(f"Warning: 跳过一个解析失败的excluded_item: {str(e)}")
            continue

    # 构建批次对象
    batch = AgentDecisionBatch(
        decisions=decisions,
        excluded_items=excluded_items,
        document_summary=response_dict.get('document_summary', 'No summary provided'),
        processing_metadata={
            'total_items_in_material': len(decisions) + len(excluded_items),
            'decisions_count': len(decisions),
            'excluded_count': len(excluded_items)
        }
    )

    return batch


# ============================================
# Agent类
# ============================================

class BillingAgent:
    """账单处理Agent"""

    def __init__(self, accounting_entity: str, use_mock: bool = True):
        """
        初始化Agent

        Args:
            accounting_entity: 记账主体
            use_mock: 是否使用模拟模式（不调用真实API）
        """
        self.accounting_entity = accounting_entity
        self.use_mock = use_mock

        if not use_mock:
            # 初始化真实的LLM
            api_key = os.getenv("DASHSCOPE_API_KEY", "")
            if not api_key or api_key == "YOUR_API_KEY_HERE":
                raise ValueError(
                    "DASHSCOPE_API_KEY未配置。"
                    "请在.env文件中设置API密钥，或使用use_mock=True"
                )

            self.llm = ChatOpenAI(
                base_url=os.getenv(
                    "QWEN_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"
                ),
                api_key=api_key,
                model=os.getenv("QWEN_MODEL", "qwen-max"),
                temperature=0
            )

            # 创建提示词模板
            self.prompt = ChatPromptTemplate.from_messages([
                ("system", AGENT_SYSTEM_PROMPT),
                ("user", USER_PROMPT_TEMPLATE)
            ])

            # 创建JSON输出解析器
            self.parser = JsonOutputParser()

            # 构建链
            self.chain = self.prompt | self.llm | self.parser
        else:
            self.llm = None
            self.chain = None

    def process_material(
        self,
        material_content: str,
        ledger: Ledger
    ) -> AgentDecisionBatch:
        """
        处理材料并给出决策

        Args:
            material_content: 材料内容
            ledger: 旧账本

        Returns:
            决策批次
        """
        if self.use_mock:
            # 模拟模式：不实际调用LLM
            raise ValueError(
                "模拟模式下应使用demo.py中的预定义场景。"
                "要处理真实文件，请设置use_mock=False并配置API密钥。"
            )

        # 格式化旧账摘要
        ledger_summary = format_ledger_summary(ledger)

        # ====== 调试输出 ======
        print("\n" + "=" * 70)
        print("📄 传递给模型的材料内容:")
        print("=" * 70)
        print(material_content[:1000])  # 打印前1000字符
        print("..." if len(material_content) > 1000 else "")
        print("\n" + "=" * 70)
        print("📚 旧账摘要:")
        print("=" * 70)
        print(ledger_summary[:500])
        print("=" * 70)
        # =====================

        # 调用LLM
        try:
            response = self.chain.invoke({
                "accounting_entity": self.accounting_entity,
                "material_content": material_content,
                "ledger_summary": ledger_summary
            })

            # ====== 调试输出 ======
            print("\n" + "=" * 70)
            print("🤖 模型返回结果:")
            print("=" * 70)
            print(json.dumps(response, indent=2, ensure_ascii=False)[:1000])
            print("=" * 70 + "\n")
            # =====================

            # 解析响应
            batch = parse_agent_response(response, self.accounting_entity)

            return batch

        except Exception as e:
            # 处理调用失败
            raise RuntimeError(f"Agent调用失败: {str(e)}")


# ============================================
# 便捷函数
# ============================================

def is_api_configured() -> bool:
    """检查API是否已配置"""
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    return api_key and api_key != "YOUR_API_KEY_HERE"
