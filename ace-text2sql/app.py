"""
ACE Text-to-SQL Streamlit Chatbot
"""
import streamlit as st
import sys
import json
import pandas as pd
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from models import TaskSpec
from orchestrator import ACEOrchestrator

# Page config
st.set_page_config(
    page_title="ACE Text-to-SQL",
    page_icon="🤖",
    layout="wide"
)

# Initialize ACE Orchestrator (cached)
@st.cache_resource
def get_orchestrator():
    return ACEOrchestrator(
        playbook_path="./data/playbook.json",
        vector_store_path="./vector_store/chroma_db"
    )

orchestrator = get_orchestrator()

# Session state
if 'history' not in st.session_state:
    st.session_state.history = []
if 'last_query' not in st.session_state:
    st.session_state.last_query = ""
if 'last_result' not in st.session_state:
    st.session_state.last_result = None
if 'show_learning_success' not in st.session_state:
    st.session_state.show_learning_success = False
if 'playbook_update_msg' not in st.session_state:
    st.session_state.playbook_update_msg = None

# Header
st.title("🤖 ACE Text-to-SQL Chatbot")
st.markdown("**Self-Improving SQL Generator** using Agentic Context Engineering")

# Show one-time playbook update message after rerun
if st.session_state.playbook_update_msg:
    st.success(st.session_state.playbook_update_msg)
    if st.session_state.last_query:
        st.info(f"🔄 Try your query again: '{st.session_state.last_query}'")
    else:
        st.info("🔄 Try your query again.")
    st.session_state.playbook_update_msg = None

# Sidebar: Playbook viewer
with st.sidebar:
    st.header("📚 SQL Playbook")

    playbook = orchestrator.context_builder.load_playbook()

    st.metric("Version", playbook.version)
    st.metric("Last Updated", playbook.last_updated[:19].replace('T', ' '))

    # Show playbook sections
    for section_name, items in playbook.sections.items():
        with st.expander(f"📖 {section_name.replace('_', ' ').title()} ({len(items)} items)"):
            for item in items:
                st.markdown(f"**{item.id}**")
                st.text(item.content[:200] + ("..." if len(item.content) > 200 else ""))
                st.caption(f"Used: {item.usage_count} | Helpful: {item.helpful} | Harmful: {item.harmful}")
                st.divider()

# Main area
st.markdown("---")

# Query input
col1, col2 = st.columns([4, 1])

with col1:
    user_query = st.text_input(
        "Enter your question about the dvdrental database:",
        placeholder="e.g., Show me the top 10 customers by revenue",
        key="query_input"
    )

with col2:
    st.write("")  # Spacer
    st.write("")  # Spacer
    generate_btn = st.button("🚀 Generate SQL", type="primary", use_container_width=True)

# Manual Learning Section (ALWAYS VISIBLE)
st.markdown("---")
with st.expander("✍️ Teach the System (Manual Learning)"):
    st.markdown("**Provide custom guidance to improve SQL generation:**")
    user_guidance = st.text_area(
        "What should the system learn?",
        placeholder="Example: Use DATE_TRUNC instead of DATE_PART for better month grouping",
        height=100,
        key="user_guidance"
    )

    if st.button("📚 Add to Playbook", type="secondary", key="add_guidance"):
        if user_guidance.strip():
            with st.spinner("💡 Learning from your guidance..."):
                from models import PlaybookItem
                playbook_obj = orchestrator.curator.load_playbook()

                new_id = f"user-{len(playbook_obj.sections['sql_patterns']):05d}"
                new_item = PlaybookItem(
                    id=new_id,
                    content=f"USER GUIDANCE: {user_guidance}",
                    usage_count=0,
                    helpful=0,
                    harmful=0
                )

                playbook_obj.sections['sql_patterns'].append(new_item)
                orchestrator.curator.save_playbook(playbook_obj)

            st.balloons()
            st.session_state.playbook_update_msg = f"✅ Playbook updated. Added as `{new_id}`"
            st.rerun()
        else:
            st.warning("Please enter guidance text")

st.markdown("---")

# Generate SQL
if generate_btn and user_query:
    with st.spinner("🔄 Generating SQL with ACE..."):
        # Create task spec
        task_spec = TaskSpec(
            user_query=user_query,
            mode="online"
        )

        # Run ACE
        run_record = orchestrator.run(task_spec)

        # Extract results
        gen_output = None
        exec_output = None
        generated_sql = ""

        for step in run_record.steps:
            if step.component == "generator":
                gen_output = step.output
                generated_sql = gen_output.get('sql', '')
            elif step.component == "executor":
                exec_output = step.output

        # Store in session state for feedback
        st.session_state.last_query = user_query
        st.session_state.last_result = {
            "gen_output": gen_output,
            "exec_output": exec_output,
            "generated_sql": generated_sql,
            "run_record": run_record,
            "task_spec": task_spec
        }

        # Store in history
        st.session_state.history.append({
            "query": user_query,
            "sql": generated_sql,
            "reasoning": gen_output.get('reasoning', '') if gen_output else '',
            "success": run_record.outcome.success,
            "execution": exec_output,
            "run_id": run_record.id
        })

    # Show learning success message if flag is set
    if st.session_state.show_learning_success:
        st.success("✅ Playbook updated with your guidance!")
        st.info(f"🔄 Try your query again: '{st.session_state.last_query}'")
        st.session_state.show_learning_success = False

    # Display results
    if gen_output or st.session_state.last_result:
        st.success("✅ SQL Generated!")

        # Show reasoning
        with st.expander("🧠 Reasoning", expanded=True):
            st.write(gen_output.get('reasoning', ''))
    else:
        st.error("❌ Failed to generate SQL. Check the logs for details.")

    # Show SQL (only if generated)
    if generated_sql:
        st.subheader("📝 Generated SQL")
        st.code(generated_sql, language="sql")

    # Show execution results
    if exec_output and exec_output.get('success'):
        st.subheader("📊 Query Results")

        rows = exec_output.get('rows', [])
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)
            st.caption(f"Returned {len(rows)} rows")
        else:
            st.info("Query executed successfully but returned no rows")

    elif exec_output:
        st.error(f"❌ SQL Execution Error: {exec_output.get('error', 'Unknown error')}")

        # Check which learning steps actually occurred
        reflection_triggered = any(step.component == "reflector" for step in run_record.steps)
        curation_triggered = any(step.component == "curator" for step in run_record.steps)

        if curation_triggered:
            # Extract what was learned
            learned_rules = []
            for step in run_record.steps:
                if step.component == "curator":
                    learning_summary = step.output.get('learning_summary', {})
                    learned_rules = learning_summary.get('rules_added', [])
                    break

            st.success("🧠 I learned from my mistake! The playbook has been updated.")

            # Show what was learned
            if learned_rules:
                with st.expander("📚 What I Learned", expanded=True):
                    for rule in learned_rules[:3]:  # Show first 3
                        section_icon = {"common_mistakes": "⚠️", "sql_patterns": "💡", "schema_rules": "📋"}.get(rule.get('section', ''), "📌")
                        st.markdown(f"{section_icon} **{rule.get('id', 'New Rule')}**")
                        content = rule.get('content', '')
                        # Show truncated content
                        if len(content) > 150:
                            st.text(content[:150] + "...")
                        else:
                            st.text(content)
                        st.divider()

            st.info("🔄 Try your query again - I'll use this new knowledge!")
            # Persist notice across next run
            st.session_state.playbook_update_msg = "✅ Playbook updated from automatic error analysis."
        elif reflection_triggered:
            st.warning("ℹ️ Error was analyzed, but no playbook update was applied. Use 'Fix & Learn' to curate a new rule.")
        else:
            st.warning("⚠️ Click 'Fix & Learn' below to trigger automatic error analysis.")

    # Feedback section
    st.markdown("---")
    st.subheader("💬 Provide Feedback (for Online Learning)")

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button("✅ Correct", use_container_width=True):
            # Re-run with correct feedback
            task_spec.user_feedback = {"status": "correct"}
            run_record = orchestrator.run(task_spec)
            st.success("✅ Feedback recorded! Playbook updated.")
            st.rerun()

    with col2:
        if st.button("❌ Incorrect", use_container_width=True):
            # Re-run with incorrect feedback
            task_spec.user_feedback = {"status": "incorrect"}
            run_record = orchestrator.run(task_spec)
            st.warning("⚠️ Feedback recorded. ACE Reflector will analyze and update playbook.")
            st.rerun()

    with col3:
        if exec_output and not exec_output.get('success'):
            if st.button("🔧 Fix & Learn from Error", use_container_width=True):
                # Trigger reflection on execution error
                with st.spinner("🤔 Analyzing error and updating playbook..."):
                    task_spec.user_feedback = {"status": "execution_error"}
                    learn_record = orchestrator.run(task_spec)

                # Check if learning happened
                learning_triggered = any(step.component == "curator" for step in learn_record.steps)

                if learning_triggered:
                    st.success("✅ I learned from my mistake! Playbook updated.")
                    st.info("💡 New rules added to prevent this error in the future.")

                    # Show what was learned
                    for step in learn_record.steps:
                        if step.component == "curator":
                            ops = step.output.get('operations', [])
                            if ops:
                                with st.expander("📚 What I Learned"):
                                    for op in ops[:3]:  # Show first 3
                                        if op['type'] == 'ADD':
                                            st.markdown(f"**Added:** {op.get('content', '')[:200]}...")

                    # Ask if user wants to retry
                    st.markdown("---")
                    if st.button("🔄 Try Again with Updated Knowledge", type="primary", use_container_width=True):
                        st.rerun()
                else:
                    st.warning("⚠️ Could not extract learning from this error. Please try manual feedback.")
                    st.stop()

# Query history
if st.session_state.history:
    st.markdown("---")
    st.subheader("📜 Query History")

    for idx, item in enumerate(reversed(st.session_state.history[-5:])):  # Show last 5
        with st.expander(f"Query {len(st.session_state.history) - idx}: {item['query'][:50]}..."):
            st.markdown(f"**Status:** {'✅ Success' if item['success'] else '❌ Failed'}")
            st.code(item['sql'], language="sql")

            if item['execution'] and item['execution']['success']:
                st.caption(f"Returned {item['execution']['row_count']} rows")

# Footer
st.markdown("---")
st.caption("🔬 ACE Text-to-SQL Prototype | Powered by GPT-4 + ChromaDB + PostgreSQL")

# Instructions
with st.expander("ℹ️ How to Use"):
    st.markdown("""
    ### Setup
    1. Ensure PostgreSQL dvdrental database is running on localhost:5432
    2. Create `.env` file with your OpenAI API key and database credentials
    3. Run `python src/rag_builder.py` to populate the vector store (first time only)

    ### Using the Chatbot
    1. Enter a natural language question about the dvdrental database
    2. Click "Generate SQL" to get the AI-generated query
    3. Review the generated SQL and execution results
    4. Provide feedback (Correct/Incorrect) to help ACE learn

    ### How ACE Learns
    - **Correct feedback**: Increments helpful counters for used playbook items
    - **Incorrect feedback**: Triggers Reflector → extracts insights → Curator updates playbook
    - **Playbook evolves**: New rules/patterns accumulate over time, improving future queries

    ### Example Queries
    - "Show me the top 10 customers by revenue"
    - "List all films with Tom Hanks"
    - "Which films have never been rented?"
    - "Average rental duration by film rating"
    - "Revenue by store last month"
    """)
