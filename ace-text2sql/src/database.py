"""
Database utilities for PostgreSQL dvdrental
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()


class DatabaseConnection:
    """PostgreSQL connection manager"""

    def __init__(self):
        self.config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "dvdrental"),
            "user": os.getenv("DB_USER", "postgres"),
            "password": os.getenv("DB_PASSWORD")
        }
        self.conn: Optional[psycopg2.extensions.connection] = None

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**self.config)
            return True
        except Exception as e:
            print(f"Database connection error: {e}")
            return False

    def disconnect(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def execute_query(self, sql: str, fetch_limit: int = 100) -> Dict[str, Any]:
        """
        Execute SQL query and return results

        Returns:
            Dict with success, rows, error, row_count
        """
        if not self.conn:
            self.connect()

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql)

                # Check if query returns rows (SELECT)
                if cur.description:
                    rows = cur.fetchmany(fetch_limit)
                    # Convert Decimal to float for JSON serialization
                    serializable_rows = []
                    for row in rows:
                        row_dict = dict(row)
                        for key, value in row_dict.items():
                            if isinstance(value, (type(None), str, int, float, bool)):
                                continue
                            elif hasattr(value, '__float__'):  # Decimal, etc.
                                row_dict[key] = float(value)
                            else:
                                row_dict[key] = str(value)
                        serializable_rows.append(row_dict)

                    return {
                        "success": True,
                        "rows": serializable_rows,
                        "row_count": cur.rowcount,
                        "error": None
                    }
                else:
                    # DML queries (INSERT, UPDATE, DELETE)
                    self.conn.commit()
                    return {
                        "success": True,
                        "rows": [],
                        "row_count": cur.rowcount,
                        "error": None
                    }
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            return {
                "success": False,
                "rows": [],
                "row_count": 0,
                "error": str(e)
            }

    def introspect_schema(self) -> Dict[str, Any]:
        """
        Extract complete schema metadata from dvdrental database

        Returns:
            Dict with tables, columns, primary_keys, foreign_keys
        """
        if not self.conn:
            self.connect()

        schema_info = {
            "tables": [],
            "columns": {},
            "primary_keys": {},
            "foreign_keys": []
        }

        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get all tables in public schema
                cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """)
                tables = [row['table_name'] for row in cur.fetchall()]
                schema_info["tables"] = tables

                # Get columns for each table
                for table in tables:
                    cur.execute("""
                        SELECT
                            column_name,
                            data_type,
                            is_nullable,
                            column_default
                        FROM information_schema.columns
                        WHERE table_schema = 'public'
                        AND table_name = %s
                        ORDER BY ordinal_position
                    """, (table,))

                    schema_info["columns"][table] = [
                        {
                            "name": row['column_name'],
                            "type": row['data_type'],
                            "nullable": row['is_nullable'] == 'YES',
                            "default": row['column_default']
                        }
                        for row in cur.fetchall()
                    ]

                # Get primary keys
                for table in tables:
                    cur.execute("""
                        SELECT kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                            ON tc.constraint_name = kcu.constraint_name
                            AND tc.table_schema = kcu.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                        AND tc.table_schema = 'public'
                        AND tc.table_name = %s
                    """, (table,))

                    pk_columns = [row['column_name'] for row in cur.fetchall()]
                    if pk_columns:
                        schema_info["primary_keys"][table] = pk_columns

                # Get foreign keys
                cur.execute("""
                    SELECT
                        tc.table_name AS from_table,
                        kcu.column_name AS from_column,
                        ccu.table_name AS to_table,
                        ccu.column_name AS to_column
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = 'public'
                """)

                schema_info["foreign_keys"] = [
                    {
                        "from_table": row['from_table'],
                        "from_column": row['from_column'],
                        "to_table": row['to_table'],
                        "to_column": row['to_column']
                    }
                    for row in cur.fetchall()
                ]

        except Exception as e:
            print(f"Schema introspection error: {e}")

        return schema_info

    def get_sample_data(self, table: str, limit: int = 5) -> List[Dict]:
        """Get sample rows from a table"""
        result = self.execute_query(f"SELECT * FROM {table} LIMIT {limit}")
        return result.get("rows", [])


# Singleton instance
db = DatabaseConnection()
