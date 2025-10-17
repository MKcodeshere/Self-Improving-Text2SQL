"""
ACE Text-to-SQL Data Models
"""
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


class TaskSpec(BaseModel):
    """Task specification for SQL generation"""
    goal: str = "Generate SQL from natural language query"
    user_query: str
    constraints: Optional[List[str]] = None
    mode: Literal["online"] = "online"  # Prototype uses online mode only
    user_feedback: Optional[Dict[str, Any]] = None


class Outcome(BaseModel):
    """Execution outcome"""
    success: bool
    score: float = 0.0
    sql_valid: bool = False
    results_correct: Optional[bool] = None

class StepRecord(BaseModel):
    """Individual step execution record"""
    component: str
    output: Dict[str, Any]
    latency_ms: float
    tokens: int = 0


class RunRecord(BaseModel):
    """Complete run trace for episodic memory"""
    id: str = Field(default_factory=lambda: f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
    task_spec: TaskSpec
    steps: List[StepRecord] = []
    artifacts: Dict[str, str] = {}  # component -> artifact_id
    outcome: Outcome
    metrics: Dict[str, Any] = {}
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class Artifact(BaseModel):
    """Versioned artifact (context, playbook, critique)"""
    id: str
    kind: Literal["context_chain", "playbook", "critique", "insight"]
    content: Any
    refs: Optional[List[str]] = None
    metrics: Optional[Dict[str, float]] = None
    version: str = "1.0"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class ScoreCard(BaseModel):
    """Evaluation rubrics and scores"""
    run_id: str
    rubrics: Dict[str, float] = {
        "sql_validity": 0.0,
        "semantic_correctness": 0.0,
        "efficiency": 0.0,
        "safety": 0.0
    }
    overall_score: float = 0.0
    notes: List[str] = []
    promote: bool = False


class PlaybookItem(BaseModel):
    """Individual playbook bullet"""
    id: str
    content: str
    usage_count: int = 0
    helpful: int = 0
    harmful: int = 0


class SQLPlaybook(BaseModel):
    """Complete SQL playbook structure"""
    id: str = "sql_playbook_v1"
    version: str = "1.0.0"
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())
    sections: Dict[str, List[PlaybookItem]] = {
        "schema_rules": [],
        "sql_patterns": [],
        "common_mistakes": []
    }


class CuratorOperation(BaseModel):
    """Delta operation for playbook updates"""
    type: Literal["ADD", "UPDATE", "DELETE"]
    section: Literal["schema_rules", "sql_patterns", "common_mistakes"]
    id: Optional[str] = None
    content: Optional[str] = None
    field: Optional[Literal["helpful", "harmful", "usage_count"]] = None
    increment: Optional[int] = None


class ReflectorInsight(BaseModel):
    """Insight extracted by Reflector"""
    error_identification: str
    error_category: Literal["syntax", "join_error", "aggregation", "schema_misunderstanding", "logic_error", "none"]
    root_cause: str
    correct_sql: Optional[str] = None
    key_insight: Optional[Dict[str, str]] = None  # {type, content}
    playbook_feedback: Optional[Dict[str, Literal["helpful", "harmful"]]] = None


class ContextChain(BaseModel):
    """Assembled context for Generator"""
    id: str = Field(default_factory=lambda: f"ctx_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    version: str = "1.0"
    token_budget: int = 8000
    segments: List[Dict[str, Any]] = []
    total_tokens: int = 0
