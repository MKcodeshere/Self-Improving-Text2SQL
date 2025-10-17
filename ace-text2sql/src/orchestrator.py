"""
ACE Orchestrator: Coordinates Generator → Reflector → Curator
"""
import json
import time
from typing import Dict, Any
from models import TaskSpec, RunRecord, StepRecord, Outcome
from components import ContextBuilder, Generator, Reflector, Curator, Evaluator
from rag_builder import RAGBuilder
from database import db


class EpisodicMemory:
    """Simple JSON-based episodic memory"""

    def __init__(self, filepath: str = "./data/episodic_memory.jsonl"):
        self.filepath = filepath

    def log(self, run_record: RunRecord):
        """Append run record to episodic memory"""
        with open(self.filepath, 'a') as f:
            f.write(json.dumps(run_record.dict()) + "\n")


class ACEOrchestrator:
    """Main ACE orchestration layer"""

    def __init__(self, playbook_path: str = "./data/playbook.json",
                 vector_store_path: str = "./vector_store/chroma_db"):
        # Initialize components
        self.rag = RAGBuilder(persist_path=vector_store_path)
        self.context_builder = ContextBuilder(self.rag, playbook_path)
        self.generator = Generator()
        self.reflector = Reflector()
        self.curator = Curator(playbook_path)
        self.evaluator = Evaluator()
        self.episodic_memory = EpisodicMemory()

        # Connect to database
        db.connect()

    def run(self, task_spec: TaskSpec) -> RunRecord:
        """
        Execute complete ACE cycle: Generate → Execute → Reflect → Curate

        Returns: RunRecord with full trace
        """
        run_record = RunRecord(
            task_spec=task_spec.dict() if hasattr(task_spec, 'dict') else task_spec,
            outcome=Outcome(success=False)
        )

        try:
            # Step 1: Context Building
            start_time = time.time()
            context_chain = self.context_builder.build_context(task_spec.user_query)
            context_latency = (time.time() - start_time) * 1000

            run_record.steps.append(StepRecord(
                component="context_builder",
                output={"context_id": context_chain.id, "tokens": context_chain.total_tokens},
                latency_ms=context_latency,
                tokens=context_chain.total_tokens
            ))

            # Step 2: SQL Generation
            start_time = time.time()
            gen_result = self.generator.generate(context_chain)
            gen_latency = (time.time() - start_time) * 1000

            run_record.steps.append(StepRecord(
                component="generator",
                output=gen_result,
                latency_ms=gen_latency,
                tokens=1000  # Estimate
            ))

            generated_sql = gen_result.get('sql', '')

            # Step 3: SQL Execution
            start_time = time.time()
            execution_result = db.execute_query(generated_sql)
            exec_latency = (time.time() - start_time) * 1000

            run_record.steps.append(StepRecord(
                component="executor",
                output=execution_result,
                latency_ms=exec_latency,
                tokens=0
            ))

            # Step 4: Evaluation
            user_feedback = task_spec.user_feedback.get('status') if task_spec.user_feedback else None
            scorecard = self.evaluator.evaluate(generated_sql, execution_result, user_feedback)

            run_record.outcome = Outcome(
                success=execution_result['success'],
                score=scorecard['overall_score'],
                sql_valid=execution_result['success'],
                results_correct=(user_feedback == "correct") if user_feedback else None
            )

            # Step 5: Auto-curation on errors (Curator-first, then Reflector→Curator once if needed)
            should_autocurate = (
                user_feedback == "incorrect" or
                not execution_result['success'] or
                (execution_result.get('error') and 'operator does not exist' in execution_result.get('error', ''))
            )

            if should_autocurate:
                any_curated = False
                learning_summary = None

                # 5a. Curator-first: generate operations directly from error context
                start_time = time.time()
                ops = self.curator.curate_from_error(
                    task_spec.user_query,
                    generated_sql,
                    execution_result.get('error', '')
                )
                if ops:
                    self.curator.apply_operations(ops)
                    curate_latency = (time.time() - start_time) * 1000
                    
                    # Extract learning summary for UI
                    learning_summary = {
                        "learned_from": "error_analysis",
                        "rules_added": [{"section": op.section, "id": op.id, "content": op.content} for op in ops]
                    }

                    run_record.steps.append(StepRecord(
                        component="curator",
                        output={
                            "operations": [op.dict() for op in ops],
                            "learning_summary": learning_summary
                        },
                        latency_ms=curate_latency,
                        tokens=500
                    ))
                    any_curated = True

                # 5b. If still nothing, Reflector → Curator (single attempt)
                if not any_curated:
                    start_time = time.time()
                    playbook = self.context_builder.load_playbook()
                    insight = self.reflector.reflect(
                        task_spec.user_query,
                        generated_sql,
                        execution_result,
                        playbook,
                        user_feedback or "execution_error"
                    )
                    reflect_latency = (time.time() - start_time) * 1000

                    run_record.steps.append(StepRecord(
                        component="reflector",
                        output=insight.dict(),
                        latency_ms=reflect_latency,
                        tokens=800
                    ))

                    start_time = time.time()
                    operations = self.curator.curate([insight]) if insight.key_insight else []
                    if operations:
                        self.curator.apply_operations(operations)
                        curate_latency = (time.time() - start_time) * 1000
                        
                        # Extract learning summary for UI
                        learning_summary = {
                            "learned_from": "reflection_analysis",
                            "rules_added": [{"section": op.section, "id": op.id, "content": op.content} for op in operations]
                        }

                        run_record.steps.append(StepRecord(
                            component="curator",
                            output={
                                "operations": [op.dict() for op in operations],
                                "learning_summary": learning_summary
                            },
                            latency_ms=curate_latency,
                            tokens=500
                        ))

            # Calculate metrics
            run_record.metrics = {
                "total_tokens": sum(step.tokens for step in run_record.steps),
                "total_latency_ms": sum(step.latency_ms for step in run_record.steps),
                "cost_usd": sum(step.tokens for step in run_record.steps) * 0.00001  # Rough estimate
            }

            # Log to episodic memory
            self.episodic_memory.log(run_record)

        except Exception as e:
            print(f"Orchestrator error: {e}")
            run_record.outcome = Outcome(success=False, score=0.0)

        return run_record

    def close(self):
        """Cleanup connections"""
        db.disconnect()
