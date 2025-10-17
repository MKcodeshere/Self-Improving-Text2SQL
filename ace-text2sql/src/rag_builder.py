"""
RAG Builder: Populates ChromaDB with dvdrental schema metadata
"""
import os
import chromadb
from chromadb.config import Settings
from langchain_openai import OpenAIEmbeddings
from typing import Dict, List
from dotenv import load_dotenv
from database import db

load_dotenv()


class RAGBuilder:
    """Builds and manages the semantic memory (vector store)"""

    def __init__(self, persist_path: str = "./vector_store/chroma_db"):
        self.persist_path = persist_path
        # Initialize OpenAI embeddings
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small"
        )

        # Initialize ChromaDB client
        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name="dvdrental_schema",
            metadata={"description": "DVD rental database schema and metadata"}
        )

    def build_schema_documents(self, schema_info: Dict) -> List[Dict]:
        """
        Convert schema introspection into searchable documents

        Returns list of {id, document, metadata} dicts
        """
        documents = []

        # 1. Table-level documents
        for table in schema_info["tables"]:
            columns = schema_info["columns"].get(table, [])
            pk_columns = schema_info["primary_keys"].get(table, [])

            col_desc = ", ".join([
                f"{col['name']} ({col['type']}{'PK' if col['name'] in pk_columns else ''})"
                for col in columns
            ])

            doc_text = (
                f"Table: {table}\n"
                f"Columns: {col_desc}\n"
                f"Primary Key: {', '.join(pk_columns) if pk_columns else 'None'}\n"
                f"Description: Database table for {table.replace('_', ' ')}"
            )

            documents.append({
                "id": f"table_{table}",
                "document": doc_text,
                "metadata": {
                    "type": "schema",
                    "table": table,
                    "pk": ",".join(pk_columns)
                }
            })

        # 2. Foreign key / JOIN pattern documents
        fk_by_relationship = {}
        for fk in schema_info["foreign_keys"]:
            key = f"{fk['from_table']}_{fk['to_table']}"
            if key not in fk_by_relationship:
                fk_by_relationship[key] = []
            fk_by_relationship[key].append(fk)

        for idx, (key, fks) in enumerate(fk_by_relationship.items()):
            fk = fks[0]  # Use first FK for relationship
            doc_text = (
                f"JOIN Pattern: {fk['from_table']} → {fk['to_table']}\n"
                f"Relationship: {fk['from_table']}.{fk['from_column']} = {fk['to_table']}.{fk['to_column']}\n"
                f"SQL Example: JOIN {fk['to_table']} ON {fk['from_table']}.{fk['from_column']} = {fk['to_table']}.{fk['to_column']}"
            )

            documents.append({
                "id": f"join_{key}",
                "document": doc_text,
                "metadata": {
                    "type": "join_pattern",
                    "from_table": fk['from_table'],
                    "to_table": fk['to_table'],
                    "from_column": fk['from_column'],
                    "to_column": fk['to_column']
                }
            })

        # 3. Business rules (domain knowledge for dvdrental)
        business_rules = [
            {
                "id": "rule_revenue_calculation",
                "document": "Business Rule: Customer revenue is calculated by summing payment.amount. Use customer → rental → payment JOIN chain.",
                "metadata": {"type": "business_rule", "topic": "revenue"}
            },
            {
                "id": "rule_film_availability",
                "document": "Business Rule: Film availability requires checking inventory. Use film → inventory → rental to check if film is currently rented.",
                "metadata": {"type": "business_rule", "topic": "availability"}
            },
            {
                "id": "rule_active_customers",
                "document": "Business Rule: Filter customers by active=1 (integer column, where 1=active, 0=inactive) unless explicitly querying inactive customers.",
                "metadata": {"type": "business_rule", "topic": "customer_status"}
            }
        ]
        documents.extend(business_rules)

        # 4. Common SQL patterns (few-shot examples)
        sql_examples = [
            {
                "id": "example_customer_revenue",
                "document": """Example Query: Show top 10 customers by total revenue
SQL:
SELECT
    c.customer_id,
    c.first_name || ' ' || c.last_name AS customer_name,
    SUM(p.amount) AS total_revenue
FROM customer c
JOIN rental r ON c.customer_id = r.customer_id
JOIN payment p ON r.rental_id = p.rental_id
GROUP BY c.customer_id, c.first_name, c.last_name
ORDER BY total_revenue DESC
LIMIT 10;""",
                "metadata": {"type": "example", "category": "aggregation", "tables": "customer,rental,payment"}
            },
            {
                "id": "example_film_actor_join",
                "document": """Example Query: List all films with their actors
SQL:
SELECT
    f.title,
    a.first_name || ' ' || a.last_name AS actor_name
FROM film f
JOIN film_actor fa ON f.film_id = fa.film_id
JOIN actor a ON fa.actor_id = a.actor_id
ORDER BY f.title, actor_name;""",
                "metadata": {"type": "example", "category": "many_to_many", "tables": "film,actor,film_actor"}
            },
            {
                "id": "example_left_join",
                "document": """Example Query: Count rentals per film (including films never rented)
SQL:
SELECT
    f.film_id,
    f.title,
    COUNT(r.rental_id) AS rental_count
FROM film f
LEFT JOIN inventory i ON f.film_id = i.film_id
LEFT JOIN rental r ON i.inventory_id = r.inventory_id
GROUP BY f.film_id, f.title
ORDER BY rental_count DESC;""",
                "metadata": {"type": "example", "category": "left_join", "tables": "film,inventory,rental"}
            }
        ]
        documents.extend(sql_examples)

        return documents

    def populate_vector_store(self):
        """
        Main method: Introspect database and populate ChromaDB
        """
        print("🔍 Introspecting dvdrental database...")
        db.connect()
        schema_info = db.introspect_schema()
        db.disconnect()

        print(f"✅ Found {len(schema_info['tables'])} tables, {len(schema_info['foreign_keys'])} foreign keys")

        print("📝 Building searchable documents...")
        documents = self.build_schema_documents(schema_info)
        print(f"✅ Created {len(documents)} documents")

        print("🚀 Populating ChromaDB vector store...")
        ids = [doc["id"] for doc in documents]
        doc_texts = [doc["document"] for doc in documents]
        metadatas = [doc["metadata"] for doc in documents]

        # Embed and store
        embeddings = self.embeddings.embed_documents(doc_texts)

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=doc_texts,
            metadatas=metadatas
        )

        print(f"✅ Successfully populated vector store at {self.persist_path}")
        print(f"   Total documents: {self.collection.count()}")

    def query(self, query_text: str, k: int = 5) -> List[Dict]:
        """
        Query the vector store

        Returns list of {id, document, metadata, distance}
        """
        query_embedding = self.embeddings.embed_query(query_text)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k
        )

        documents = []
        for i in range(len(results['ids'][0])):
            documents.append({
                "id": results['ids'][0][i],
                "document": results['documents'][0][i],
                "metadata": results['metadatas'][0][i],
                "distance": results['distances'][0][i] if 'distances' in results else None
            })

        return documents


if __name__ == "__main__":
    # Initialize and populate
    rag = RAGBuilder()
    rag.populate_vector_store()

    # Test query
    print("\n🧪 Testing RAG retrieval...")
    test_query = "How to calculate customer revenue?"
    results = rag.query(test_query, k=3)

    print(f"\nQuery: '{test_query}'")
    print("Top 3 results:")
    for i, doc in enumerate(results, 1):
        print(f"\n{i}. [{doc['metadata']['type']}] {doc['id']}")
        print(f"   {doc['document'][:200]}...")
