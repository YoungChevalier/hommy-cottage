"""
Hommy Cottage - 15 Demonstration Queries Verification Tests
Validates sql/07_queries.sql:
1. File structure, numbering, Question & Concept documentation
2. Live execution of all 15 queries against database seed data
"""
from pathlib import Path


def test_queries_file_structure():
    """Verify sql/07_queries.sql contains 15 numbered queries with Question and Concept comments."""
    queries_path = Path("sql/07_queries.sql")
    assert queries_path.exists(), "sql/07_queries.sql must exist"
    content = queries_path.read_text(encoding="utf-8")

    # Verify all 15 query headers
    for i in range(1, 16):
        assert f"Query {i}:" in content, f"Header for Query {i} missing"

    # Verify presence of questions and concepts
    assert content.count("Question:") == 15, "Each of the 15 queries must have a Question comment"
    assert content.count("Concept:") == 15, "Each of the 15 queries must have a Concept comment"

    # Required concept keywords
    concepts = [
        "INNER JOIN",
        "LEFT JOIN",
        "GROUP BY",
        "HAVING",
        "Subquery",
        "Correlated Subquery",
        "NOT EXISTS",
        "Relational Division",
        "Window Function",
        "CTE",
        "DATEDIFF",
        "CASE",
        "UNION",
        "LIMIT",
        "EXPLAIN"
    ]
    for c in concepts:
        assert c.lower() in content.lower(), f"Concept '{c}' must be covered in sql/07_queries.sql"


def test_all_15_queries_execute_on_seed_data(app):
    """Executes all 15 queries from sql/07_queries.sql directly on the seed data to guarantee correctness."""
    from db import query_all

    queries_path = Path("sql/07_queries.sql")
    content = queries_path.read_text(encoding="utf-8")

    # Split queries by semicolon, filtering out comments and USE statements
    lines = content.splitlines()
    buffer = []
    queries = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("#"):
            continue
        buffer.append(line)
        current = "\n".join(buffer).strip()
        if current.endswith(";"):
            stmt = current[:-1].strip()
            buffer = []
            if stmt and not stmt.upper().startswith("USE "):
                queries.append(stmt)

    assert len(queries) == 15, f"Expected 15 executable SQL queries, found {len(queries)}"

    with app.app_context():
        for idx, sql_query in enumerate(queries, 1):
            try:
                results = query_all(sql_query)
                assert isinstance(results, (list, tuple)), f"Query {idx} did not return a list or tuple"
                # Every query should produce at least 1 row on the seed data
                assert len(results) > 0, f"Query {idx} returned 0 rows on seed data:\n{sql_query}"
            except Exception as e:
                raise AssertionError(f"Query {idx} failed during execution:\n{sql_query}\nError: {e}")
