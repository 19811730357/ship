"""Public workflow facade. Demo and file modes share the same billing engine."""
from pathlib import Path
import re

from .models import Ledger


class BillingWorkflow:
    def __init__(self, accounting_entity, use_mock_data=True, agent=None, parser=None):
        self.accounting_entity = accounting_entity
        self.use_mock_data = use_mock_data
        self.agent, self.parser = agent, parser
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from .workflow_db import DatabaseWorkflow
            self._engine = DatabaseWorkflow(self.accounting_entity, self.use_mock_data,
                                            db_config={"database": ":memory:"},
                                            agent=self.agent, parser=self.parser)
        return self._engine

    def process_real_files(self, file_paths, ledger_data=None, output_dir=None, force_reprocess=False,
                           preview_only=True, allow_updates=False):
        return self._get_engine().process_real_files(
            file_paths, ledger_data=ledger_data, output_dir=output_dir,
            force_reprocess=force_reprocess, preview_only=preview_only, allow_updates=allow_updates)

    def commit_preview(self, preview_id, review_actions=None):
        return self._get_engine().commit_preview(preview_id, review_actions)

    def process_demo_scenario(self, scenario_name, output_dir=None):
        from .demo import get_demo_ledger, get_demo_scenario
        engine = self._get_engine()
        # Each demonstration is an isolated synthetic baseline, never the configured live database.
        if engine.db.load_ledger(self.accounting_entity).records:
            engine.close()
            from .workflow_db import DatabaseWorkflow
            engine = self._engine = DatabaseWorkflow(self.accounting_entity, True, db_config={"database": ":memory:"})
        ledger = get_demo_ledger()
        for record in ledger.records:
            record.financial_attributes.accounting_entity = self.accounting_entity
            engine.db.save_ledger_record(record)
        batch = get_demo_scenario(scenario_name)
        sources = {}
        for decision in batch.decisions:
            decision.financial_attributes.accounting_entity = self.accounting_entity
            for evidence in decision.evidence:
                key = evidence.source_file
                view = sources.setdefault(key, {"source_id": key, "source_file": key, "source_type": "synthetic_demo",
                                                "blocks": [], "content": ""})
                evidence.source_id = key
                evidence.block_id = f"{key}:{len(view['blocks'])}"
                view["blocks"].append({"source_id": key, "block_id": evidence.block_id, "text": evidence.original_text})
                view["content"] += evidence.original_text + "\n"
            for view in sources.values():
                header = f"Synthetic fixture: {decision.document_info.document_number} {decision.transaction_party.issuer}"
                view["blocks"].append({"source_id": view["source_id"], "block_id": view["source_id"] + ":identity",
                                       "text": header})
                view["content"] += header + "\n"
            # Revision facts are explicitly authored in these synthetic fixtures.
            revision = [e for e in decision.evidence if re.search("修改|调整|改为|revise", e.original_text)]
            decision.revision_requested = bool(revision)
            decision.revision_evidence = revision
        return engine.prepare_batch(batch, list(sources.values()), allow_updates=True, output_dir=output_dir,
                                    files_processed=1)

    def _combine_parsed_content(self, parsed_list):
        return self._get_engine()._combine_parsed_content(parsed_list)

    def close(self):
        if self._engine is not None:
            self._engine.close()
            self._engine = None


def run_demo_workflow(scenario_name, output_dir="output"):
    workflow = BillingWorkflow("Demo Origin", True)
    preview = workflow.process_demo_scenario(scenario_name, Path(output_dir) / scenario_name)
    return workflow.commit_preview(preview["preview_id"])
