# ACE Text-to-SQL Prototype

**Self-Improving Natural Language to SQL System** using Agentic Context Engineering (ACE) framework.

## Overview

This prototype implements the ACE framework for Text-to-SQL generation with the PostgreSQL dvdrental database. The system continuously improves SQL generation quality through an evolving **SQL Playbook** maintained by three specialized components:

- **Generator**: Produces SQL using GPT-4 + RAG (ChromaDB schema retrieval) + Playbook
- **Reflector**: Analyzes SQL outcomes, extracts insights from errors/successes
- **Curator**: Updates playbook with incremental delta operations (ADD/UPDATE/DELETE)

### Key Features

✅ **Schema-aware generation** via RAG (no training data required)
✅ **Self-improving playbook** that accumulates SQL patterns and error fixes
✅ **Online learning** from user feedback (correct/incorrect)
✅ **Episodic memory** logging all query attempts
✅ **Explainable** reasoning traces and playbook items
✅ **Interactive chatbot** interface with Streamlit

---

## Architecture

```
┌────────────────────────────────────────────────────┐
│         ACE Orchestrator                           │
│  ┌─────────┐  ┌──────────┐  ┌────────┐            │
│  │Generator│→│Reflector │→│Curator │            │
│  └─────────┘  └──────────┘  └────────┘            │
└──────┬──────────────┬───────────────┬─────────────┘
       │              │               │
   PostgreSQL    ChromaDB       SQL Playbook
   dvdrental     (Schema RAG)   (versioned JSON)
```

---

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ with dvdrental database
- OpenAI API key (GPT-4 access)

### 1. Clone/Download

```bash
cd /mnt/c/research/ace-text2sql
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Create `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
OPENAI_API_KEY=sk-...
DB_HOST=localhost
DB_PORT=5432
DB_NAME=dvdrental
DB_USER=postgres
DB_PASSWORD=your_password
```

### 4. Set Up dvdrental Database

If you don't have the dvdrental database:

```bash
# Download
wget https://www.postgresqltutorial.com/wp-content/uploads/2019/05/dvdrental.zip
unzip dvdrental.zip

# Restore
createdb dvdrental
pg_restore -U postgres -d dvdrental dvdrental.tar
```

Verify:
```bash
psql -U postgres -d dvdrental -c "SELECT COUNT(*) FROM customer;"
```

### 5. Initialize Vector Store (First Time Only)

```bash
python src/rag_builder.py
```

This will:
- Introspect dvdrental schema (tables, columns, foreign keys)
- Generate searchable documents for ChromaDB
- Populate vector store with schema metadata, JOIN patterns, SQL examples

Expected output:
```
🔍 Introspecting dvdrental database...
✅ Found 15 tables, 21 foreign keys
📝 Building searchable documents...
✅ Created 45 documents
🚀 Populating ChromaDB vector store...
✅ Successfully populated vector store at ./vector_store/chroma_db
   Total documents: 45
```

---

## Usage

### Run the Streamlit Chatbot

```bash
streamlit run app.py
```

The chatbot UI will open at `http://localhost:8501`

### Using the Chatbot

1. **Enter a natural language query**
   ```
   Show me the top 10 customers by revenue
   ```

2. **Click "Generate SQL"**
   - ACE generates SQL using RAG + playbook
   - SQL is executed on dvdrental database
   - Results are displayed

3. **Provide feedback**
   - ✅ **Correct**: Increments helpful counters for used playbook items
   - ❌ **Incorrect**: Triggers Reflector → Curator → playbook update

4. **Watch playbook evolve**
   - Check sidebar to see playbook items grow
   - New rules/patterns accumulate over time

### Example Queries

```
- Show me the top 10 customers by revenue
- List all films with Tom Hanks
- Which films have never been rented?
- Average rental duration by film rating
- Total revenue by store
- How many rentals per customer?
- Films in the Action category with rating R
```

**📝 See [TEST_QUERIES.md](TEST_QUERIES.md) for comprehensive test scenarios that demonstrate the self-improving feedback loop!**

---

## How ACE Learning Works

### Offline Mode (Not used in prototype)
- Would train on query/SQL pairs with multi-epoch adaptation
- Playbook grows from curated examples

### Online Mode (Prototype uses this)

**Correct feedback flow:**
```
User: "Show top customers"
Generator: Produces SQL using playbook
Executor: Returns results
User: ✅ Correct
→ Curator: Increment helpful counters for used items
```

**Incorrect feedback flow:**
```
User: "Show top customers"
Generator: Produces SQL using playbook
Executor: Returns wrong results
User: ❌ Incorrect
→ Reflector: Analyze error, extract insight
→ Curator: Generate delta operations (ADD/UPDATE)
→ Playbook: New rule added (e.g., "ts-00004: Missing LEFT JOIN causes zero counts to disappear")
```

### Memory Architecture

1. **Semantic Memory (ChromaDB)**
   - Schema metadata (tables, columns, PKs, FKs)
   - JOIN patterns
   - Business rules
   - Few-shot SQL examples

2. **Procedural Memory (playbook.json)**
   - Schema rules (relationships)
   - SQL patterns (templates)
   - Common mistakes (troubleshooting)

3. **Episodic Memory (episodic_memory.jsonl)**
   - Full traces of every query
   - Used for debugging and analysis

---

## Project Structure

```
ace-text2sql/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment template
├── app.py                       # Streamlit chatbot UI
│
├── data/
│   ├── playbook.json            # SQL Playbook (versioned, evolves)
│   └── episodic_memory.jsonl    # Query execution logs
│
├── vector_store/
│   └── chroma_db/               # ChromaDB persistent storage
│
├── src/
│   ├── models.py                # Pydantic data models
│   ├── database.py              # PostgreSQL connection + introspection
│   ├── rag_builder.py           # ChromaDB initialization
│   ├── components.py            # Generator, Reflector, Curator, Evaluator
│   └── orchestrator.py          # ACE orchestration layer
│
└── logs/                        # (optional) structured logs
```

---

## Technical Details

### Components

**1. Context Builder**
- Queries ChromaDB for relevant schema (RAG)
- Loads SQL Playbook
- Assembles context chain with token budget

**2. Generator**
- LangChain + GPT-4-turbo
- Input: Context chain + user query
- Output: `{reasoning, sql, playbook_ids_used, tables_accessed}`

**3. Reflector**
- Analyzes SQL generation outcomes
- Compares with execution results + user feedback
- Extracts insights: `{error_category, root_cause, key_insight}`

**4. Curator**
- Generates delta operations: `ADD`, `UPDATE`, `DELETE`
- Applies operations to playbook
- Prevents context collapse via incremental updates

**5. Evaluator**
- Scores SQL with rubrics: validity, correctness, efficiency, safety
- Determines promotion eligibility

### Data Flow

```
User Query
   ↓
Context Builder (RAG + Playbook)
   ↓
Generator (GPT-4) → SQL
   ↓
PostgreSQL Executor → Results
   ↓
Evaluator → ScoreCard
   ↓
[If feedback provided]
   ↓
Reflector → Insights
   ↓
Curator → Delta Ops → Playbook Updated
   ↓
Episodic Memory (logged)
```

---

## Monitoring Playbook Evolution

### View Playbook

```bash
cat data/playbook.json | jq '.sections.common_mistakes'
```

### View Episodic Memory

```bash
tail -f data/episodic_memory.jsonl | jq '.'
```

### Playbook Metrics

Check sidebar in Streamlit app:
- **Version**: Playbook semantic version
- **Item counts**: Schema rules, SQL patterns, common mistakes
- **Usage stats**: helpful/harmful counters per item

---

## Troubleshooting

### Database connection error
```
Error: could not connect to server
```
**Fix**: Check PostgreSQL is running, verify credentials in `.env`

### OpenAI API error
```
Error: invalid API key
```
**Fix**: Set valid `OPENAI_API_KEY` in `.env`

### ChromaDB not populated
```
Warning: No documents found in vector store
```
**Fix**: Run `python src/rag_builder.py` first

### Module import errors
```
ModuleNotFoundError: No module named 'langchain'
```
**Fix**: `pip install -r requirements.txt`

---

## Future Enhancements

- [ ] Offline batch training mode with query/SQL pairs
- [ ] Multi-epoch adaptation with bandit optimization
- [ ] Policy/Governor for PII redaction and safety
- [ ] Advanced Planner with Plan DSL
- [ ] PostgreSQL episodic memory (replace JSONL)
- [ ] A/B testing for playbook versions
- [ ] Explainability dashboard (trace viewer)
- [ ] Support for multiple databases (MySQL, SQLite)

---

## References

- **ACE Research Paper**: "Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models"
- **Technical Design**: `ACE_Text2SQL_Technical_Design.md`
- **dvdrental Database**: [PostgreSQL Tutorial](https://www.postgresqltutorial.com/postgresql-getting-started/postgresql-sample-database/)

---

## License

MIT License - Free for research and prototyping

---

**Built with ACE Framework | GPT-4 + LangChain + ChromaDB + PostgreSQL**
