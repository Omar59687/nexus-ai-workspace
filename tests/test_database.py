from nexus_ai.database import check_database_connection


def test_database_connection_executes_sql() -> None:
    result = check_database_connection()

    assert result == 1
