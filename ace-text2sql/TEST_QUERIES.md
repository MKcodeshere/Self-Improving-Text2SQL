# ACE Text-to-SQL Test Queries

This document explains how the feedback mechanism works and provides test queries to demonstrate the system's self-improving capabilities.

---

## How the Feedback System Works

### ✅ **Correct Feedback** (When you click "Correct")

**What happens:**
1. Orchestrator re-runs with `user_feedback = "correct"`
2. **Evaluator** scores the query higher (semantic_correctness = 1.0)
3. **No Reflector/Curator triggered** (system assumes everything worked well)
4. Playbook items that were used get their `helpful` counter incremented
5. **Timestamp updates** to show when feedback was recorded

**Use case:** When the SQL is correct and results match your expectations.

---

### ❌ **Incorrect Feedback** (When you click "Incorrect")

**What happens:**
1. Orchestrator re-runs with `user_feedback = "incorrect"`
2. **Reflector is triggered** to analyze the error:
   - Compares generated SQL vs execution results
   - Identifies error type (JOIN error, aggregation issue, schema misunderstanding, etc.)
   - Extracts root cause
   - Proposes correct SQL approach
   - Generates a **key insight** for the playbook
3. **Curator processes the insight**:
   - Reviews current playbook
   - Generates delta operations (ADD/UPDATE/DELETE)
   - **Adds new rules** to `common_mistakes` section
   - **Adds new patterns** to `sql_patterns` section
   - **Updates counters** (helpful/harmful) for existing items
4. **Playbook is saved** with updated timestamp
5. **Next query benefits** from the new knowledge

**Use case:** When the SQL is wrong, returns incorrect results, or uses suboptimal logic.

---

## Test Queries That Will Trigger Playbook Updates

### Category 1: LEFT JOIN vs INNER JOIN Issues

#### Query 1: Films Never Rented
```
Show me all films that have never been rented
```

**Why it might fail initially:**
- System might use `INNER JOIN` instead of `LEFT JOIN`
- This excludes films with 0 rentals

**Expected error:** Returns empty set or only rented films

**What the system learns after "Incorrect" feedback:**
- Adds rule: `"MISTAKE: Using INNER JOIN between film and rental excludes unrented films → FIX: Use LEFT JOIN and filter WHERE rental_id IS NULL"`
- Adds pattern: LEFT JOIN template for zero-count queries
- Timestamp updates to show playbook was modified

---

#### Query 2: Customers Who Never Rented
```
List all customers who have never made a rental
```

**Why it might fail:**
- Uses `INNER JOIN customer → rental`
- Excludes customers with no rentals

**What the system learns:**
- Adds rule about LEFT JOIN for zero-relationship queries
- Increments harmful counter for any playbook item that suggested INNER JOIN

---

### Category 2: Aggregation & GROUP BY Errors

#### Query 3: Film Rental Counts
```
Show me the rental count for each film including films never rented
```

**Why it might fail:**
- Missing `GROUP BY f.film_id, f.title`
- PostgreSQL will throw error: "column must appear in GROUP BY clause"

**What the system learns:**
- Adds rule: `"PostgreSQL requires ALL non-aggregated SELECT columns in GROUP BY"`
- Adds pattern: Correct GROUP BY template with COUNT and multiple columns

---

#### Query 4: Customer Revenue Without All Columns in GROUP BY
```
Calculate total revenue per customer with their full name
```

**Why it might fail:**
- Groups by `customer_id` only but selects `first_name`, `last_name`
- PostgreSQL error: "must appear in GROUP BY"

**What the system learns:**
- Reinforces GROUP BY rule
- Adds example showing functional dependency doesn't exempt columns

---

### Category 3: Date/Time Handling

#### Query 5: Rentals Last Month
```
Show me all rentals from last month
```

**Why it might fail:**
- Incorrect date filtering (e.g., using string comparison instead of date functions)
- Wrong PostgreSQL date syntax

**What the system learns:**
- Adds pattern: `"Use DATE_TRUNC('month', rental_date) for monthly filtering"`
- Adds rule about PostgreSQL date functions

---

#### Query 6: Overdue Rentals
```
List all overdue rentals (rental_date + rental_duration < today)
```

**Why it might fail:**
- Schema misunderstanding (dvdrental doesn't have rental_duration in rental table)
- Should use `film.rental_duration` via JOIN

**What the system learns:**
- Adds schema rule: `"rental_duration is in film table, not rental table"`
- Adds JOIN pattern: `rental → inventory → film` for rental duration queries

---

### Category 4: Many-to-Many Relationships

#### Query 7: Films by Actor
```
List all films starring 'PENELOPE GUINESS'
```

**Why it might fail:**
- Direct JOIN `film → actor` (missing bridge table)
- Should be `film → film_actor → actor`

**What the system learns:**
- Adds rule: `"film ↔ actor is M:N via film_actor bridge table"`
- Adds JOIN pattern template for M:N relationships

---

#### Query 8: Film Categories
```
Show me all Action films
```

**Why it might fail:**
- Direct JOIN `film → category` (missing bridge table)
- Should be `film → film_category → category`

**What the system learns:**
- Adds rule about film_category bridge table
- Adds pattern for category filtering

---

### Category 5: Suboptimal SQL (Efficiency Issues)

#### Query 9: Top Customers by Revenue Using Subquery
```
Show me customers who have spent more than the average customer
```

**Why it might be suboptimal:**
- System might use correlated subquery instead of window function
- Performance issue on large datasets

**What the system learns:**
- Adds pattern: Window function approach with `AVG() OVER()`
- Adds efficiency rule about avoiding correlated subqueries

---

### Category 6: Business Logic Errors

#### Query 10: Active Customers Only
```
List all customers and their email addresses
```

**Why it might be incomplete:**
- Doesn't filter by `active = TRUE`
- Returns inactive customers

**What the system learns:**
- Adds business rule: `"Filter customers by active=TRUE unless explicitly querying inactive"`
- Timestamp updates

---

## Testing Protocol

### Step-by-Step Testing

1. **Start with Query 1** ("Show me all films that have never been rented")
2. Click "Generate SQL"
3. Review the generated SQL
4. If SQL uses `INNER JOIN film → inventory → rental`:
   - Click **"❌ Incorrect"**
   - Wait 5-10 seconds for Reflector/Curator
   - Check sidebar → **"Last Updated"** timestamp should change
   - Check **"Common Mistakes"** section → should have new item added
5. **Run Query 1 again** (same question)
6. Generated SQL should now use `LEFT JOIN` with `WHERE rental_id IS NULL`
7. Click **"✅ Correct"**
8. Check sidebar → timestamp updates again, helpful counter increments

### Expected Playbook Growth

**Before testing:**
- Schema Rules: 4 items
- SQL Patterns: 2 items
- Common Mistakes: 3 items
- **Total: 9 items**

**After testing all 10 queries with incorrect feedback:**
- Schema Rules: ~7 items (+3)
- SQL Patterns: ~6 items (+4)
- Common Mistakes: ~8 items (+5)
- **Total: ~21 items (+12)**

**Timestamp should update 10+ times** as playbook evolves

---

## Verification Checklist

✅ Timestamp updates after "Incorrect" feedback
✅ New items appear in playbook sections
✅ Helpful/harmful counters increment
✅ Same query generates better SQL after learning
✅ Episodic memory logs all attempts (`data/episodic_memory.jsonl`)

---

## What Happens Behind the Scenes (Incorrect Feedback Flow)

```
User clicks "❌ Incorrect"
    ↓
Orchestrator.run(user_feedback="incorrect")
    ↓
Evaluator: scores semantic_correctness = 0.0
    ↓
[Trigger Reflection]
    ↓
Reflector (GPT-4 analysis):
    - Reviews generated SQL
    - Compares with execution result
    - Identifies error category (e.g., "join_error")
    - Extracts key insight:
      {
        "type": "common_mistake",
        "content": "MISTAKE: Using INNER JOIN excludes films with zero rentals → FIX: Use LEFT JOIN"
      }
    ↓
Curator (GPT-4 review):
    - Reads current playbook
    - Reviews Reflector insight
    - Generates operations:
      [
        {
          "type": "ADD",
          "section": "common_mistakes",
          "id": "ts-00004",
          "content": "MISTAKE: Using INNER JOIN between film and rental excludes unrented films → FIX: Use LEFT JOIN and filter WHERE rental_id IS NULL"
        }
      ]
    ↓
Curator.apply_operations():
    - Adds new PlaybookItem to common_mistakes section
    - Updates playbook.last_updated = NOW()
    - Saves playbook.json
    ↓
Episodic Memory:
    - Logs full RunRecord to episodic_memory.jsonl
    ↓
Streamlit UI:
    - Reloads playbook
    - Shows updated timestamp
    - Displays new playbook item in sidebar
```

---

## Advanced Testing: Multi-Round Learning

Try this sequence to see compound learning:

1. **Query:** "Show films never rented" → Click Incorrect → Learns LEFT JOIN
2. **Query:** "Show customers who never rented" → Should now use LEFT JOIN (learned from #1)
3. **Query:** "Count rentals per film including zero" → Should use LEFT JOIN + GROUP BY
4. **Query:** "Calculate revenue by customer" → Should use correct GROUP BY with all columns

Each query builds on previous learning!

---

## Monitoring Playbook Evolution

### View playbook changes in real-time:
```bash
# Watch timestamp updates
watch -n 2 "cat data/playbook.json | jq -r '.last_updated'"

# Count total playbook items
cat data/playbook.json | jq '[.sections[]] | add | length'

# View latest episodic memory entry
tail -1 data/episodic_memory.jsonl | jq '.'
```

### Check helpful/harmful counters:
```bash
cat data/playbook.json | jq '.sections.common_mistakes[] | {id, helpful, harmful}'
```

---

## Expected Output Examples

### Before Learning (Query 1)
```sql
-- Generated SQL (WRONG - uses INNER JOIN)
SELECT f.film_id, f.title
FROM film f
JOIN inventory i ON f.film_id = i.film_id
JOIN rental r ON i.inventory_id = r.inventory_id
WHERE r.rental_id IS NULL;

-- Result: Empty (incorrect)
```

### After "Incorrect" Feedback
**Playbook updated:**
```json
{
  "id": "ts-00004",
  "content": "MISTAKE: Using INNER JOIN between film and rental excludes unrented films → FIX: Use LEFT JOIN and filter WHERE rental_id IS NULL",
  "usage_count": 0,
  "helpful": 0,
  "harmful": 0
}
```

**Timestamp:** `2025-10-16 17:45:32` (updated!)

### After Re-Running Query 1
```sql
-- Generated SQL (CORRECT - uses LEFT JOIN)
SELECT f.film_id, f.title
FROM film f
LEFT JOIN inventory i ON f.film_id = i.film_id
LEFT JOIN rental r ON i.inventory_id = r.inventory_id
WHERE r.rental_id IS NULL
GROUP BY f.film_id, f.title;

-- Result: 42 films (correct)
```

Click "✅ Correct" → helpful counter increments, timestamp updates again

---

**This is the ACE self-improvement loop in action!**
