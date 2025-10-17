"""
ACE Components: Generator, Reflector, Curator, Evaluator, Context Builder
"""
import os
import json
from typing import Dict, List, Any, Optional
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from dotenv import load_dotenv
from models import (
    SQLPlaybook, PlaybookItem, CuratorOperation,
    ReflectorInsight, ContextChain
)
from rag_builder import RAGBuilder

load_dotenv()


class ContextBuilder:
    """Assembles context chains from RAG + Playbook"""

    def __init__(self, rag: RAGBuilder, playbook_path: str):
        self.rag = rag
        self.playbook_path = playbook_path

    def load_playbook(self) -> SQLPlaybook:
        """Load current playbook from JSON"""
        if os.path.exists(self.playbook_path):
            with open(self.playbook_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return SQLPlaybook(**data)
        return SQLPlaybook()

    def build_context(self, user_query: str, token_budget: int = 8000) -> ContextChain:
        """
        Build context chain with RAG retrieval + Playbook

        Returns ContextChain object
        """
        context = ContextChain(token_budget=token_budget)

        # 1. System prompt
        context.segments.append({
            "type": "system",
            "content": "You are an expert PostgreSQL SQL generator for the dvdrental database (DVD rental store).",
            "tokens": 20
        })

        # 2. RAG retrieval (schema, joins, examples)
        rag_results = self.rag.query(user_query, k=5)
        schema_docs = [doc['document'] for doc in rag_results]
        schema_text = "\n\n".join(schema_docs)

        context.segments.append({
            "type": "schema",
            "content": schema_text,
            "tokens": int(len(schema_text.split()) * 1.3)  # Rough token estimate
        })

        # 3. Playbook (relevant bullets)
        playbook = self.load_playbook()
        all_bullets = []
        for section_items in playbook.sections.values():
            all_bullets.extend(section_items)

        playbook_text = "SQL PLAYBOOK (Curated Strategies):\n"
        for item in all_bullets[:10]:  # Top 10 bullets
            playbook_text += f"\n[{item.id}] {item.content}\n"

        context.segments.append({
            "type": "playbook",
            "content": playbook_text,
            "tokens": int(len(playbook_text.split()) * 1.3)
        })

        # 4. Constraints
        context.segments.append({
            "type": "constraints",
            "content": (
                "CONSTRAINTS:\n"
                "- Use PostgreSQL syntax only\n"
                "- **PLAYBOOK RULES ARE ABSOLUTE** - Even if the user query suggests something that violates a playbook MISTAKE rule, you MUST follow the FIX instead\n"
                "- **COMMON_MISTAKES section overrides user requests that would cause errors**\n"
                "- Always use explicit JOIN conditions\n"
                "- Include table aliases for clarity\n"
                "- Return JSON: {reasoning, sql, playbook_ids_used, tables_accessed}"
            ),
            "tokens": 80
        })

        # 5. User query
        context.segments.append({
            "type": "user_query",
            "content": f"USER QUERY: {user_query}",
            "tokens": int(len(user_query.split()) * 1.3)
        })

        context.total_tokens = sum(seg['tokens'] for seg in context.segments)
        return context


class Generator:
    """SQL generation component using LangChain + GPT-4"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4.1",
            temperature=0.0,
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )

    def generate(self, context_chain: ContextChain) -> Dict[str, Any]:
        """
        Generate SQL from context chain

        Returns: {reasoning, sql, playbook_ids_used, tables_accessed}
        """
        # Build prompt from context chain
        system_content = ""
        user_content = ""

        for segment in context_chain.segments:
            if segment['type'] == 'system':
                system_content += segment['content'] + "\n\n"
            else:
                user_content += segment['content'] + "\n\n"

        user_content += "\nOUTPUT (JSON):\n{\"reasoning\": \"...\", \"sql\": \"...\", \"playbook_ids_used\": [...], \"tables_accessed\": [...]}"

        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content)
        ]

        response = self.llm.invoke(messages)
        result_text = response.content

        # Parse JSON response
        try:
            # Extract JSON from markdown code block if present
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)
            return result
        except json.JSONDecodeError:
            # Fallback: return raw text
            return {
                "reasoning": "Failed to parse JSON response",
                "sql": result_text,
                "playbook_ids_used": [],
                "tables_accessed": []
            }


class Evaluator:
    """Evaluates SQL quality with rubrics"""

    def evaluate(self, sql: str, execution_result: Dict, user_feedback: Optional[str] = None) -> Dict[str, float]:
        """
        Score SQL using rubrics

        Returns: {rubrics, overall_score, notes, promote}
        """
        rubrics = {
            "sql_validity": 1.0 if execution_result['success'] else 0.0,
            "semantic_correctness": 1.0 if user_feedback == "correct" else 0.5,  # Assume neutral if no feedback
            "efficiency": 0.8,  # Placeholder
            "safety": 1.0 if not any(kw in sql.upper() for kw in ['DROP', 'DELETE', 'TRUNCATE']) else 0.0
        }

        overall_score = sum(rubrics.values()) / len(rubrics)

        notes = []
        if execution_result['success']:
            notes.append(f"SQL executed successfully, returned {execution_result['row_count']} rows")
        else:
            notes.append(f"SQL failed: {execution_result['error']}")

        if user_feedback == "correct":
            notes.append("User confirmed correct results")
        elif user_feedback == "incorrect":
            notes.append("User reported incorrect results")

        return {
            "rubrics": rubrics,
            "overall_score": overall_score,
            "notes": notes,
            "promote": overall_score >= 0.75
        }


class Reflector:
    """Analyzes SQL generation outcomes and extracts insights"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model="gpt-4.1",
            temperature=0.0,
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )

    def reflect(self, user_query: str, generated_sql: str,
                execution_result: Dict, playbook: SQLPlaybook,
                user_feedback: Optional[str] = None) -> ReflectorInsight:
        """
        Analyze SQL generation and extract insights

        Returns: ReflectorInsight object
        """
        # Build reflection prompt
        system_prompt = """You are a SQL Analysis Expert. Analyze the SQL generation outcome and extract insights.

Your tasks:
1. Identify what went wrong (if anything)
2. Diagnose root cause
3. Suggest correct approach
4. Extract key insight for the playbook
5. Provide feedback on playbook items

If the SQL was correct, still extract useful insights about what worked well."""

        user_prompt = f"""USER QUERY: {user_query}

GENERATED SQL:
{generated_sql}

EXECUTION STATUS: {'SUCCESS' if execution_result['success'] else 'FAILED'}
{'ERROR: ' + execution_result['error'] if not execution_result['success'] else ''}
ROWS RETURNED: {execution_result.get('row_count', 0)}

USER FEEDBACK: {user_feedback or 'None'}

CURRENT PLAYBOOK:
{json.dumps({k: [item.dict() for item in v[:3]] for k, v in playbook.sections.items()}, indent=2)}

OUTPUT (JSON):
{{
  "error_identification": "...",
  "error_category": "syntax|join_error|aggregation|schema_misunderstanding|logic_error|none",
  "root_cause": "...",
  "correct_sql": "...",
  "key_insight": {{"type": "schema_rule|sql_pattern|common_mistake", "content": "..."}},
  "playbook_feedback": {{"item_id": "helpful|harmful"}}
}}"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = self.llm.invoke(messages)
        result_text = response.content

        # Parse JSON
        try:
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)
            return ReflectorInsight(**result)
        except Exception as e:
            # Fallback
            return ReflectorInsight(
                error_identification="Failed to parse reflection",
                error_category="none",
                root_cause="Parsing error",
                key_insight=None
            )


class Curator:
    """Updates playbook with delta operations"""

    def __init__(self, playbook_path: str):
        self.playbook_path = playbook_path
        self.llm = ChatOpenAI(
            model="gpt-4.1",
            temperature=0.0,
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )

    def load_playbook(self) -> SQLPlaybook:
        """Load playbook from JSON"""
        if os.path.exists(self.playbook_path):
            with open(self.playbook_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return SQLPlaybook(**data)
        return SQLPlaybook()

    def save_playbook(self, playbook: SQLPlaybook):
        """Save playbook to JSON"""
        from datetime import datetime
        playbook.last_updated = datetime.now().isoformat()
        with open(self.playbook_path, 'w', encoding='utf-8') as f:
            json.dump(playbook.dict(), f, indent=2, ensure_ascii=False)

    def check_semantic_similarity(self, new_content: str, existing_items: List[PlaybookItem], section: str) -> tuple:
        """
        Use LLM to check if new rule is semantically similar to existing rules.
        
        Returns: (is_similar: bool, similar_item: PlaybookItem or None, should_merge: bool)
        """
        if not existing_items:
            return (False, None, False)
        
        # Build prompt for LLM to compare rules
        system_prompt = (
            "You are a SQL playbook curator. Your task is to determine if a new rule is semantically similar "
            "to any existing rules in the playbook, even if worded differently.\n\n"
            "Rules are considered SIMILAR if they address the same mistake or pattern, even with different examples.\n"
            "For example:\n"
            "- 'Comparing integer to boolean' and 'Using boolean with integer column' are SIMILAR\n"
            "- 'Using INNER JOIN' and 'Forgetting GROUP BY' are DIFFERENT\n\n"
            "Respond with JSON only."
        )
        
        existing_rules_text = "\n".join([
            f"{i+1}. [{item.id}] {item.content[:200]}"
            for i, item in enumerate(existing_items[-10:])  # Check last 10 rules only
        ])
        
        user_prompt = (
            f"SECTION: {section}\n\n"
            f"NEW RULE TO ADD:\n{new_content}\n\n"
            f"EXISTING RULES IN PLAYBOOK:\n{existing_rules_text}\n\n"
            "OUTPUT (JSON):\n"
            "{\n"
            "  \"is_similar\": true/false,\n"
            "  \"similar_to_id\": \"<id of most similar existing rule, or null>\",\n"
            "  \"similarity_reason\": \"<brief explanation>\",\n"
            "  \"should_merge\": true/false,  // true if new rule should update/replace existing\n"
            "  \"recommended_content\": \"<merged/improved content if should_merge is true, else null>\"\n"
            "}"
        )
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = self.llm.invoke(messages)
            result_text = response.content
            
            # Parse JSON
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(result_text)
            
            if result.get('is_similar') and result.get('similar_to_id'):
                # Find the similar item
                similar_item = None
                for item in existing_items:
                    if item.id == result['similar_to_id']:
                        similar_item = item
                        break
                
                return (
                    True,
                    similar_item,
                    result.get('should_merge', False)
                )
            
            return (False, None, False)
            
        except Exception as e:
            print(f"LLM similarity check error: {e}")
            return (False, None, False)

    def curate(self, insights: List[ReflectorInsight]) -> List[CuratorOperation]:
        """
        Generate delta operations from insights

        Returns: List of CuratorOperation
        """
        playbook = self.load_playbook()

        # Build curation prompt
        system_prompt = """You are the SQL Playbook Curator. Review reflections and update the playbook.

Generate delta operations (ADD, UPDATE, DELETE) to improve the playbook.
Focus on quality over quantity.

SECTION GUIDELINES:
- 'common_mistakes': Use format 'MISTAKE: <wrong approach> → FIX: <correct approach>'
  Example: 'MISTAKE: Using EXTRACT in WHERE clause → FIX: Use DATE_TRUNC for better index usage'
- 'sql_patterns': Provide complete SQL code examples with comments
  Example: '-- Revenue by month template\nSELECT DATE_TRUNC(\'month\', payment_date) AS month, SUM(amount) ...'
- 'schema_rules': Describe table relationships and constraints
  Example: 'payment.rental_id → rental.rental_id (N:1 relationship, payments reference rentals)'

IMPORTANT: Generate IDs in format: ts-##### for common_mistakes, code-##### for sql_patterns, sr-##### for schema_rules"""

        insights_text = "\n\n".join([
            f"Insight {i+1}:\n{json.dumps(insight.dict(), indent=2)}"
            for i, insight in enumerate(insights)
        ])

        user_prompt = f"""CURRENT PLAYBOOK:
{json.dumps(playbook.dict(), indent=2)}

RECENT INSIGHTS:
{insights_text}

OUTPUT (JSON):
{{
  "reasoning": "<Explain what pattern was identified and why this rule helps>",
  "operations": [
    {{"type": "ADD", "section": "common_mistakes", "id": "ts-#####", "content": "MISTAKE: ... → FIX: ..."}}
  ]
}}

NOTE: Prefer 'common_mistakes' for error patterns. Use 'sql_patterns' only if you have a complete working SQL template."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = self.llm.invoke(messages)
        result_text = response.content

        # Parse operations
        try:
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)
            operations = [CuratorOperation(**op) for op in result.get('operations', [])]
            
            # Store reasoning for UI display
            if operations and 'reasoning' in result:
                if hasattr(operations[0], '__dict__'):
                    operations[0]._reasoning = result['reasoning']
            
            return operations
        except Exception as e:
            print(f"Curator parsing error: {e}")
            return []

    def apply_operations(self, operations: List[CuratorOperation]):
        """Apply delta operations to playbook with LLM-based semantic duplicate detection"""
        playbook = self.load_playbook()

        for op in operations:
            section = playbook.sections.get(op.section, [])

            if op.type == "ADD":
                # Validate and normalize content based on section
                content = op.content or ""
                
                # Format validation and normalization
                if op.section == "common_mistakes":
                    # Ensure MISTAKE → FIX format
                    if "MISTAKE:" not in content:
                        # Auto-format if not in correct format
                        if "→" in content or "->" in content:
                            content = f"MISTAKE: {content}"
                        else:
                            content = f"MISTAKE: {content} → FIX: Review and apply proper pattern"
                    # Normalize arrow
                    content = content.replace("->", "→")
                    
                elif op.section == "sql_patterns":
                    # Ensure it has SQL code (contains SELECT, INSERT, UPDATE, DELETE, or WITH)
                    sql_keywords = ["SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "CREATE"]
                    if not any(kw in content.upper() for kw in sql_keywords):
                        print(f"Warning: sql_patterns entry '{op.id}' doesn't contain SQL code. Skipping.")
                        continue
                
                # Use LLM-based semantic similarity check
                print(f"Checking for semantic duplicates in {op.section}...")
                is_similar, similar_item, should_merge = self.check_semantic_similarity(
                    content, 
                    section, 
                    op.section
                )
                
                if is_similar and similar_item:
                    print(f"✓ Found similar rule: '{similar_item.id}' is semantically similar to new rule.")
                    
                    if should_merge:
                        # Update existing rule with better content
                        print(f"✓ Merging into existing rule '{similar_item.id}'")
                        similar_item.content = content  # Use new content (usually more detailed)
                        similar_item.usage_count += 1
                    else:
                        # Just increment usage
                        print(f"✓ Incrementing usage count for '{similar_item.id}'")
                        similar_item.usage_count += 1
                    
                    continue  # Skip adding new rule
                
                # No duplicate found - add new rule
                # Generate new ID with proper prefix
                existing_ids = [item.id for item in section]
                if not op.id:
                    # Auto-generate ID based on section
                    prefix_map = {
                        "common_mistakes": "ts",
                        "sql_patterns": "code",
                        "schema_rules": "sr"
                    }
                    prefix = prefix_map.get(op.section, "item")
                    new_id = f"{prefix}-{len(section)+1:05d}"
                else:
                    new_id = op.id
                    # Validate ID format
                    expected_prefix = {"common_mistakes": "ts", "sql_patterns": "code", "schema_rules": "sr"}.get(op.section)
                    if expected_prefix and not new_id.startswith(expected_prefix):
                        # Fix the prefix
                        new_id = f"{expected_prefix}-{len(section)+1:05d}"

                section.append(PlaybookItem(
                    id=new_id,
                    content=content,
                    usage_count=1,  # Start at 1 since we're using it now
                    helpful=0,
                    harmful=0
                ))
                print(f"✓ Added new rule '{new_id}' to {op.section}")

            elif op.type == "UPDATE":
                for item in section:
                    if item.id == op.id:
                        if op.field == "helpful":
                            item.helpful += op.increment or 1
                        elif op.field == "harmful":
                            item.harmful += op.increment or 1
                        elif op.field == "usage_count":
                            item.usage_count += op.increment or 1

            elif op.type == "DELETE":
                playbook.sections[op.section] = [
                    item for item in section if item.id != op.id
                ]

        self.save_playbook(playbook)
        return playbook

    def curate_from_error(self, user_query: str, generated_sql: str, error_message: str) -> List[CuratorOperation]:
        """
        LLM-driven fallback: Generate curation operations directly from the SQL error context.

        Returns: List of CuratorOperation
        """
        playbook = self.load_playbook()

        system_prompt = (
            "You are the SQL Playbook Curator. Given a failed SQL execution with its error, "
            "produce high-quality delta operations (ADD/UPDATE/DELETE) to improve the playbook. "
            "Write actionable, generalizable rules that would prevent the same error in the future.\n\n"
            "SECTION GUIDELINES:\n"
            "- 'common_mistakes': Use format 'MISTAKE: <wrong approach> → FIX: <correct approach>'\n"
            "  Example: 'MISTAKE: Using DATE() = '2023-01-01' → FIX: Use DATE_TRUNC for date comparisons'\n"
            "- 'sql_patterns': Provide complete SQL code examples with comments\n"
            "  Example: '-- Revenue by month template\\nSELECT DATE_TRUNC(\\'month\\', date) ...'\n"
            "- 'schema_rules': Describe table relationships and constraints\n"
            "  Example: 'customer.customer_id → rental.customer_id (1:N relationship)'\n\n"
            "IMPORTANT: Generate IDs in format: ts-##### for common_mistakes, code-##### for sql_patterns, sr-##### for schema_rules"
        )

        user_prompt = (
            f"USER QUERY:\n{user_query}\n\n"
            f"GENERATED SQL:\n{generated_sql}\n\n"
            f"ERROR MESSAGE:\n{error_message}\n\n"
            f"CURRENT PLAYBOOK (JSON):\n{json.dumps(playbook.dict(), indent=2)}\n\n"
            "OUTPUT (JSON):\n"
            "{\n"
            "  \"reasoning\": \"<Explain the root cause and why this rule will help>\",\n"
            "  \"operations\": [\n"
            "    {\"type\": \"ADD\", \"section\": \"common_mistakes\", \"id\": \"ts-#####\", \"content\": \"MISTAKE: ... → FIX: ...\"}\n"
            "  ]\n"
            "}\n"
            "\nNOTE: Focus on 'common_mistakes' section for errors. Only add to 'sql_patterns' if you have a complete working SQL example."
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        response = self.llm.invoke(messages)
        result_text = response.content

        try:
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            result = json.loads(result_text)
            ops = [CuratorOperation(**op) for op in result.get('operations', [])]
            
            # Store reasoning for UI display
            if ops and 'reasoning' in result:
                # Add reasoning as metadata to first operation
                if hasattr(ops[0], '__dict__'):
                    ops[0]._reasoning = result['reasoning']
            
            return ops
        except Exception as e:
            print(f"Curator-from-error parsing error: {e}")
            return []
