"""
完整工作流
串联解析、Agent决策、验证和最终操作
"""

from typing import List, Optional, Dict, Any
import json
from pathlib import Path
from datetime import datetime

from .models import (
    AgentDecisionBatch,
    FinalOperation,
    Ledger,
    RunReport,
    ProcessingResult
)
from .validator import Validator
from .ledger import (
    resolve_operation,
    apply_operation,
    load_ledger_from_dict,
    generate_processing_results
)
from .demo import get_demo_ledger, get_demo_scenario


class BillingWorkflow:
    """账单处理工作流"""

    def __init__(
        self,
        accounting_entity: str,
        use_mock_data: bool = True
    ):
        """
        初始化工作流

        Args:
            accounting_entity: 记账主体
            use_mock_data: 是否使用模拟数据（不调用真实API）
        """
        self.accounting_entity = accounting_entity
        self.use_mock_data = use_mock_data
        self.validator = Validator(accounting_entity)

    def process_demo_scenario(
        self,
        scenario_name: str,
        output_dir: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        处理演示场景

        Args:
            scenario_name: 场景名称 (update, ambiguous, create, conditional)
            output_dir: 输出目录

        Returns:
            处理结果摘要
        """
        # 获取演示数据
        ledger = get_demo_ledger()
        agent_batch = get_demo_scenario(scenario_name)

        # 处理决策
        final_operations = self._process_decisions(agent_batch, ledger)

        # 生成输出
        results = self._generate_outputs(
            final_operations,
            agent_batch,
            ledger,
            output_dir
        )

        return results

    def process_real_files(
        self,
        file_paths: List[Path],
        ledger_data: Optional[Dict[str, Any]],
        output_dir: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        处理真实文件

        Args:
            file_paths: 文件路径列表
            ledger_data: 旧账数据（字典或None）
            output_dir: 输出目录

        Returns:
            处理结果摘要
        """
        from .parsers import DocumentParser
        from .agent import BillingAgent
        from .integrations import OCRAdapter

        # 加载旧账
        if ledger_data:
            ledger = load_ledger_from_dict(ledger_data, self.accounting_entity)
        else:
            ledger = Ledger(accounting_entity=self.accounting_entity)

        # 初始化OCR适配器
        ocr_adapter = OCRAdapter()
        ocr_enabled = ocr_adapter.is_configured()

        # 初始化解析器和Agent
        parser = DocumentParser(
            ocr_enabled=ocr_enabled,
            ocr_adapter=ocr_adapter if ocr_enabled else None
        )
        agent = BillingAgent(
            accounting_entity=self.accounting_entity,
            use_mock=self.use_mock_data
        )

        # 解析所有文件
        all_parsed_content = []
        file_errors = []
        files_succeeded = 0
        ocr_calls = 0

        for file_path in file_paths:
            try:
                parsed = parser.parse_file(Path(file_path))
                all_parsed_content.append(parsed)
                files_succeeded += 1

                # 统计OCR调用
                if parsed.get('metadata', {}).get('ocr_processed'):
                    ocr_calls += 1

            except Exception as e:
                file_errors.append({
                    'file': str(file_path),
                    'error': str(e)
                })

        if not all_parsed_content:
            raise ValueError("没有成功解析任何文件")

        # 合并所有内容
        combined_content = self._combine_parsed_content(all_parsed_content)

        # 调用Agent进行决策
        try:
            agent_batch = agent.process_material(combined_content, ledger)
        except Exception as e:
            raise RuntimeError(f"Agent处理失败: {str(e)}")

        # 处理决策
        final_operations = self._process_decisions(agent_batch, ledger)

        # 生成输出
        results = self._generate_outputs(
            final_operations,
            agent_batch,
            ledger,
            output_dir
        )

        # 更新运行报告中的文件统计
        results['run_report']['files_processed'] = len(file_paths)
        results['run_report']['files_succeeded'] = files_succeeded
        results['run_report']['files_failed'] = len(file_errors)
        results['run_report']['file_errors'] = file_errors
        results['run_report']['ocr_calls'] = ocr_calls
        results['run_report']['ocr_configured'] = ocr_enabled

        return results

    def _combine_parsed_content(self, parsed_list: List[Dict[str, Any]]) -> str:
        """
        合并多个解析结果为一个文本

        Args:
            parsed_list: 解析结果列表

        Returns:
            合并后的文本内容
        """
        parts = []

        for idx, parsed in enumerate(parsed_list, 1):
            parts.append(f"=== 文件 {idx}: {parsed['source_file']} ===")
            parts.append(f"类型: {parsed['source_type']}")

            # 添加元数据
            if parsed.get('metadata'):
                parts.append("\n元数据:")
                for key, value in parsed['metadata'].items():
                    if value:
                        parts.append(f"  {key}: {value}")

            # 添加内容
            parts.append("\n内容:")
            parts.append(parsed['content'])

            # 附件信息
            if parsed.get('attachments'):
                parts.append(f"\n附件: {len(parsed['attachments'])}个")
                for att in parsed['attachments']:
                    parts.append(f"  - {att.get('filename', 'unknown')}")

            parts.append("\n" + "=" * 60 + "\n")

        return "\n".join(parts)

    def _process_decisions(
        self,
        agent_batch: AgentDecisionBatch,
        ledger: Ledger
    ) -> List[FinalOperation]:
        """
        处理Agent的决策批次

        Args:
            agent_batch: Agent决策批次
            ledger: 当前账本

        Returns:
            最终操作列表
        """
        final_operations = []

        for decision in agent_batch.decisions:
            # 程序验证
            validation_result = self.validator.validate_decision(decision, ledger)

            # 冲突解决
            final_op = resolve_operation(decision, validation_result, ledger)

            final_operations.append(final_op)

            # 如果是可应用的操作，更新账本（用于后续决策）
            if final_op.operation in ["CREATE", "UPDATE", "NO_CHANGE"]:
                ledger = apply_operation(final_op, ledger)

        return final_operations

    def _generate_outputs(
        self,
        final_operations: List[FinalOperation],
        agent_batch: AgentDecisionBatch,
        original_ledger: Ledger,
        output_dir: Optional[Path]
    ) -> Dict[str, Any]:
        """
        生成输出文件

        Args:
            final_operations: 最终操作列表
            agent_batch: Agent决策批次
            original_ledger: 原始账本
            output_dir: 输出目录

        Returns:
            处理结果摘要
        """
        # 生成处理结果
        processing_results = generate_processing_results(final_operations)

        # 应用所有操作生成快照
        ledger_snapshot = original_ledger
        for final_op in final_operations:
            ledger_snapshot = apply_operation(final_op, ledger_snapshot)

        # 生成运行报告
        run_report = self._generate_run_report(
            final_operations,
            agent_batch,
            ledger_snapshot
        )

        # 如果指定了输出目录，写入文件
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

            # 写入处理结果
            with open(output_dir / "processing_results.json", "w", encoding="utf-8") as f:
                json.dump(processing_results, f, indent=2, ensure_ascii=False, default=str)

            # 写入账本快照
            with open(output_dir / "ledger_snapshot.json", "w", encoding="utf-8") as f:
                json.dump(
                    ledger_snapshot.model_dump(),
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str
                )

            # 写入运行报告
            with open(output_dir / "run_report.json", "w", encoding="utf-8") as f:
                json.dump(
                    run_report.model_dump(),
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str
                )

        return {
            "processing_results": processing_results,
            "ledger_snapshot": ledger_snapshot.model_dump(),
            "run_report": run_report.model_dump(),
            "summary": {
                "total_decisions": len(final_operations),
                "operations": run_report.operations_summary,
                "excluded_items": len(agent_batch.excluded_items)
            }
        }

    def _generate_run_report(
        self,
        final_operations: List[FinalOperation],
        agent_batch: AgentDecisionBatch,
        ledger_snapshot: Ledger
    ) -> RunReport:
        """生成运行报告"""

        # 统计操作
        operations_summary = {
            "CREATE": 0,
            "UPDATE": 0,
            "NO_CHANGE": 0,
            "PENDING_REVIEW": 0
        }

        for final_op in final_operations:
            operations_summary[final_op.operation] += 1

        return RunReport(
            files_processed=1,
            files_succeeded=1,
            files_failed=0,
            operations_summary=operations_summary,
            excluded_items=agent_batch.excluded_items,
            file_errors=[],
            model_calls=1 if not self.use_mock_data else 0,
            ocr_calls=0,
            api_errors=0,
            using_mock_data=self.use_mock_data,
            model_configured=not self.use_mock_data,
            ocr_configured=False
        )


def run_demo_workflow(scenario_name: str, output_dir: str = "output") -> Dict[str, Any]:
    """
    运行演示工作流的便捷函数

    Args:
        scenario_name: 场景名称
        output_dir: 输出目录

    Returns:
        处理结果
    """
    workflow = BillingWorkflow(
        accounting_entity="Demo Origin",
        use_mock_data=True
    )

    return workflow.process_demo_scenario(
        scenario_name=scenario_name,
        output_dir=Path(output_dir) / scenario_name
    )
