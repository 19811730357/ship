"""
数据库集成的工作流包装器
在原有 workflow 基础上添加数据库持久化
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import uuid

from .workflow import BillingWorkflow as BaseWorkflow
from .models import LedgerRecord, Ledger


class DatabaseWorkflow(BaseWorkflow):
    """带数据库持久化的工作流"""

    def __init__(
        self,
        accounting_entity: str,
        use_mock_data: bool = True,
        db_type: str = "sqlite",
        db_config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化工作流

        Args:
            accounting_entity: 记账主体
            use_mock_data: 是否使用模拟数据
            db_type: 数据库类型 ("sqlite" 或 "postgres")
            db_config: 数据库配置
        """
        super().__init__(accounting_entity, use_mock_data)

        # 初始化数据库
        from .database import DatabaseManager
        self.db = DatabaseManager(
            db_type=db_type,
            db_config=db_config or {"database": "billing.db"}
        )
        print(f"[OK] Database connected: {db_type} - {db_config or {'database': 'billing.db'}}")

    def __del__(self):
        """清理数据库连接"""
        if hasattr(self, 'db') and self.db:
            self.db.close()

    def process_real_files(
        self,
        file_paths: List[Path],
        ledger_data: Optional[Dict[str, Any]] = None,
        output_dir: Optional[Path] = None,
        force_reprocess: bool = False
    ) -> Dict[str, Any]:
        """
        处理真实文件（使用数据库）

        Args:
            file_paths: 文件路径列表
            ledger_data: 旧账数据（如果为None，从数据库加载）
            output_dir: 输出目录
            force_reprocess: 强制重新处理（即使文件已处理过）

        Returns:
            处理结果摘要
        """
        # 初始化默认返回结构（确保始终返回完整数据）
        default_result = {
            "summary": {
                "total_decisions": 0,
                "operations": {
                    "CREATE": 0,
                    "UPDATE": 0,
                    "NO_CHANGE": 0,
                    "PENDING_REVIEW": 0
                },
                "excluded_items": 0
            },
            "processing_results": [],
            "ledger_snapshot": {
                "accounting_entity": self.accounting_entity,
                "records": []
            },
            "database_stats": {
                "total_records": 0,
                "unique_documents": 0,
                "unique_bls": 0
            },
            "session_id": str(uuid.uuid4()),
            "run_report": {
                "files_processed": 0,
                "files_succeeded": 0,
                "files_failed": 0,
                "files_skipped": 0,
                "file_errors": [],
                "ocr_calls": 0,
                "ocr_configured": False,
                "database_enabled": True
            }
        }

        try:
            from .parsers import DocumentParser
            from .agent import BillingAgent
            from .integrations import OCRAdapter

            # 初始化变量
            session_id = str(uuid.uuid4())
            results = []
            operation_counts = {
                "CREATE": 0,
                "UPDATE": 0,
                "NO_CHANGE": 0,
                "PENDING_REVIEW": 0
            }
            processing_results = []
            files_succeeded = 0
            file_errors = []
            skipped_files = []
            ocr_calls = 0
            ocr_enabled = False

            # ========================================
            # 1. 不再从数据库加载旧账（节省 token！）
            # ========================================
            # 使用空账本，让 Agent 只负责提取费用信息
            from .ledger import Ledger
            ledger = Ledger(accounting_entity=self.accounting_entity, records=[])
            print(f"[OK] Using empty ledger (smart CRUD mode)")

            # 如果用户手动上传了旧账 JSON，仍然可以使用
            if ledger_data:
                from .ledger import load_ledger_from_dict
                ledger = load_ledger_from_dict(ledger_data, self.accounting_entity)
                print(f"[OK] Loaded ledger from uploaded JSON: {len(ledger.records)} records")

            # ========================================
            # 2. 初始化 OCR 和解析器
            # ========================================
            ocr_adapter = OCRAdapter()
            ocr_enabled = ocr_adapter.is_configured()

            parser = DocumentParser(
                ocr_enabled=ocr_enabled,
                ocr_adapter=ocr_adapter if ocr_enabled else None
            )

            agent = BillingAgent(
                accounting_entity=self.accounting_entity,
                use_mock=self.use_mock_data
            )

            # ========================================
            # 3. 检查文档是否已处理
            # ========================================
            session_id = str(uuid.uuid4())
            print(f"[OK] Session ID: {session_id}")

            # ========================================
            # 4. 解析所有文件
            # ========================================
            all_parsed_content = []

            for file_path in file_paths:
                try:
                    # 检查文档是否已处理
                    with open(file_path, 'rb') as f:
                        file_content = f.read()

                    if not force_reprocess:
                        existing = self.db.check_document_processed(file_content)
                        if existing:
                            print(f"⚠️  文件已处理过: {file_path.name} (处理时间: {existing['processed_at']})")
                            skipped_files.append(str(file_path))
                            continue
                    else:
                        print(f"🔄 强制重新处理: {file_path.name}")

                    # 解析文件
                    parsed = parser.parse_file(Path(file_path))
                    all_parsed_content.append(parsed)
                    files_succeeded += 1

                    # 统计 OCR 调用
                    if parsed.get('metadata', {}).get('ocr_processed'):
                        ocr_calls += 1

                except Exception as e:
                    print(f"❌ 文件解析失败: {file_path.name} - {str(e)}")
                    file_errors.append({
                        'file': str(file_path),
                        'error': str(e)
                    })

            if not all_parsed_content:
                if skipped_files:
                    # 返回完整结构
                    default_result['summary']['total_decisions'] = 0
                    default_result['run_report']['files_skipped'] = len(skipped_files)
                    default_result['run_report']['files_processed'] = len(file_paths)
                    return default_result
                # 没有成功解析任何文件
                default_result['run_report']['files_failed'] = len(file_paths)
                default_result['run_report']['file_errors'].append({
                    'error': '没有成功解析任何文件'
                })
                return default_result

            # ========================================
            # 5. 合并内容并调用 Agent
            # ========================================
            combined_content = self._combine_parsed_content(all_parsed_content)

            print(f"\n[Agent] Calling LLM to process material...")
            print(f"[Agent] Content length: {len(combined_content)} characters")

            try:
                agent_batch = agent.process_material(combined_content, ledger)
                print(f"[Agent] ✅ Processing completed")
                print(f"[Agent] Found {len(agent_batch.decisions)} decisions")
            except Exception as e:
                print(f"[Agent] ❌ Processing failed: {e}")
                raise RuntimeError(f"Agent处理失败: {str(e)}")

            # ========================================
            # 6. 使用智能 CRUD 执行器（程序级别判断）
            # ========================================
            from .smart_crud import SmartCRUDExecutor

            crud_executor = SmartCRUDExecutor(
            db=self.db,
            accounting_entity=self.accounting_entity
            )

            print("\n" + "=" * 70)
            print("Smart CRUD Execution")
            print("=" * 70)

            results = []
            for decision in agent_batch.decisions:
                # 程序检索数据库并智能判断 CREATE/UPDATE/NO_CHANGE
                result = crud_executor.decide_and_execute(decision)
                results.append(result)

                # 保存处理历史
                self.db.save_processing_history(
                    session_id=session_id,
                    operation=result["operation"],
                    record_id=result.get("record_id"),
                    model_suggestion="EXTRACT",  # 模型只负责提取
                    model_confidence="N/A",
                    model_reasoning="Program-level decision based on database search",
                    program_validation=result["operation"],
                    final_decision=result["operation"],
                    decision_data={
                        "reason": result.get("reason"),
                        "charge_name": decision.charge_details.original_name,
                        "amount": float(decision.charge_details.amount),
                        "document_number": decision.document_info.document_number
                    }
                )

            # 统计操作类型
            operation_counts = {
                "CREATE": sum(1 for r in results if r["operation"] == "CREATE"),
                "UPDATE": sum(1 for r in results if r["operation"] == "UPDATE"),
                "NO_CHANGE": sum(1 for r in results if r["operation"] == "NO_CHANGE"),
                "PENDING_REVIEW": sum(1 for r in results if r["operation"] == "PENDING_REVIEW")
            }

            # ========================================
            # 7. 保存文档处理记录
            # ========================================
            for file_path in file_paths:
                if str(file_path) not in skipped_files:
                    try:
                        with open(file_path, 'rb') as f:
                            file_content = f.read()
                        self.db.save_document_processing(
                            file_content=file_content,
                            file_name=file_path.name,
                            status="success",
                            results={'session_id': session_id}
                        )
                    except:
                        pass

            # ========================================
            # 8. 生成输出（简化版本，不需要复杂的 final_operations）
            # ========================================
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)

            # 生成简化的摘要
            summary = {
                "total_decisions": len(results),
                "operations": operation_counts,
                "excluded_items": len(agent_batch.excluded_items) if hasattr(agent_batch, 'excluded_items') else 0
            }

            # 转换为 processing_results 格式（兼容前端）
            processing_results = []
            for result in results:
                # 处理 PENDING_REVIEW（没有record对象）
                if result["operation"] == "PENDING_REVIEW":
                    processing_results.append({
                        "operation": "PENDING_REVIEW",
                        "record_id": None,
                        "charge_details": {},
                        "document_info": {},
                        "reason": result.get("reason", "需人工审核"),
                        "validation_issues": result.get("validation_issues", {})
                    })
                    continue

                # 获取记录对象
                if result["operation"] == "CREATE":
                    record = result.get("record")
                elif result["operation"] == "UPDATE":
                    record = result.get("new_record")
                else:  # NO_CHANGE
                    record = result.get("matched_record")

                if record:
                    processing_results.append({
                        "operation": result["operation"],
                        "record_id": result.get("record_id"),
                        "charge_details": {
                            "original_name": record.charge_details.original_name,
                            "amount": float(record.charge_details.amount),
                            "currency": record.charge_details.currency,
                        },
                        "document_info": {
                            "document_number": record.document_info.document_number,
                        },
                        "reason": result.get("reason", "")
                    })

            # 添加数据库统计
            stats = self.db.get_processing_statistics(self.accounting_entity)

            # 生成账本快照（兼容前端下载功能）
            ledger_snapshot = {
                "accounting_entity": self.accounting_entity,
                "records": [
                    {
                        "record_id": r.get("record_id"),
                        "charge_name": r.get("charge_details", {}).get("original_name"),
                        "amount": r.get("charge_details", {}).get("amount"),
                        "currency": r.get("charge_details", {}).get("currency"),
                        "document_number": r.get("document_info", {}).get("document_number"),
                        "operation": r.get("operation")
                    }
                    for r in processing_results
                ]
            }

            return {
                'summary': summary,
                'processing_results': processing_results,  # 兼容前端
                'ledger_snapshot': ledger_snapshot,  # 兼容前端下载
                'database_stats': stats,
                'session_id': session_id,
                'run_report': {
                    'files_processed': len(file_paths),
                    'files_succeeded': files_succeeded,
                    'files_failed': len(file_errors),
                    'files_skipped': len(skipped_files),
                    'file_errors': file_errors,
                    'ocr_calls': ocr_calls,
                    'ocr_configured': ocr_enabled,
                    'database_enabled': True
                }
            }

        except Exception as e:
            # 发生异常时，返回默认结构 + 错误信息
            import traceback
            default_result['run_report']['files_failed'] = len(file_paths)
            default_result['run_report']['file_errors'].append({
                'error': str(e),
                'traceback': traceback.format_exc()
            })
            print(f"[ERROR] Processing failed: {e}")
            traceback.print_exc()
            return default_result

    def get_ledger_from_database(self) -> Ledger:
        """从数据库获取当前账本"""
        return self.db.load_ledger(self.accounting_entity)

    def query_by_document(self, document_number: str) -> List[LedgerRecord]:
            """按单据号查询"""
            return self.db.query_records_by_document(document_number)

    def query_by_bl(self, bill_of_lading: str) -> List[LedgerRecord]:
            """按提单号查询"""
            return self.db.query_records_by_bl(bill_of_lading)

    def get_statistics(self) -> Dict[str, Any]:
            """获取统计信息"""
            return self.db.get_processing_statistics(self.accounting_entity)
