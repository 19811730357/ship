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

AGENT_SYSTEM_PROMPT = """你是航运账单智能助手。你的任务是分析材料并给出操作建议。

**任务说明**：
分析提供的材料内容和旧账记录，为每个费用给出操作建议（CREATE/UPDATE/NO_CHANGE）。

**操作类型判断**：
- CREATE: 这是新的实际费用，旧账中没有对应记录
- UPDATE: 原文明确要修改某个费用，且能唯一匹配到旧账记录
- NO_CHANGE: 这个费用已存在于旧账，且没有变化

**重要规则**：
1. 条件收费条款（"如果...则收取"、"若超期..."）不是实际费用，应该排除到excluded_items
2. 同名费用有多条旧账时，必须有额外标识（如原金额、单据号）才能唯一匹配
3. UPDATE操作必须明确指出matched_record_id
4. 给出清晰的operation_reasoning，说明你的判断依据
5. 对于不确定的情况，设置confidence为MEDIUM或LOW

**当前记账主体**：{accounting_entity}

**输出格式要求**：
必须返回JSON对象，包含以下字段：
{{
  "decisions": [
    {{
      "suggested_operation": "CREATE|UPDATE|NO_CHANGE",
      "operation_reasoning": "决策理由",
      "matched_record_id": "旧账ID（UPDATE时必填）",
      "confidence": "HIGH|MEDIUM|LOW",
      "charge_details": {{
        "original_name": "费用名称",
        "standardized_name": "标准名称",
        "amount": 金额数字,
        "currency": "币种代码",
        "payment_method": "付款方式"
      }},
      "document_info": {{
        "document_type": "单据类型",
        "document_number": "单据号",
        "bill_of_lading": "提单号"
      }},
      "transaction_party": {{
        "issuer": "签发方",
        "recipient": "接收方"
      }},
      "financial_attributes": {{
        "posting_type": "AR|AP",
        "posting_type_reasoning": "判断依据"
      }},
      "evidence": [
        {{
          "source_file": "文件名",
          "source_type": "email_body|attachment",
          "original_text": "原文引用"
        }}
      ],
      "field_changes": {{}}
    }}
  ],
  "excluded_items": [
    {{
      "item_type": "conditional_charge|summary_line|other",
      "description": "描述",
      "reasoning": "排除原因",
      "amount": 金额或null,
      "currency": "币种或null"
    }}
  ],
  "document_summary": "整体文档摘要（可选）"
}}

注意：
- 所有金额字段使用数字类型，不要加引号
- evidence数组至少包含一个元素
- excluded_items中每个对象必须包含item_type, description, reasoning
"""

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
    decisions = []

    for dec_data in response_dict.get('decisions', []):
        try:
            # 确保必需字段存在
            charge_details_data = dec_data.get('charge_details', {})
            if not charge_details_data.get('original_name'):
                print(f"Warning: 跳过缺少费用名称的决策")
                continue
            if not charge_details_data.get('amount'):
                print(f"Warning: 跳过缺少金额的决策")
                continue

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
            decision = AgentDecision(
                suggested_operation=dec_data.get('suggested_operation', 'CREATE'),
                operation_reasoning=dec_data.get('operation_reasoning', 'No reasoning provided'),
                matched_record_id=dec_data.get('matched_record_id'),
                confidence=dec_data.get('confidence', 'MEDIUM'),
                charge_details=ChargeDetails(**charge_details_data),
                document_info=DocumentInfo(**dec_data.get('document_info', {})),
                transaction_party=TransactionParty(**dec_data.get('transaction_party', {})),
                financial_attributes=FinancialAttributes(**financial_attrs),
                evidence=[Evidence(**e) for e in evidence_list],
                field_changes=dec_data.get('field_changes')
            )
            decisions.append(decision)
        except Exception as e:
            # 跳过解析失败的决策
            print(f"Warning: 跳过一个解析失败的决策: {str(e)}")
            continue

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
