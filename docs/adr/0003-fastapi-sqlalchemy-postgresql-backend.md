# FastAPI, SQLAlchemy, and PostgreSQL backend

**Status:** Accepted

The backend uses FastAPI with Pydantic for the HTTP boundary, SQLAlchemy for persistence, Alembic for migrations, and PostgreSQL as the operational database. This combination provides typed request/response contracts, explicit transactions, versioned schema changes, and a relational foundation that can later host pgvector if that proposal is accepted.

## Consequences

- The current data layer is synchronous SQLAlchemy; async adoption is a separate decision.
- PostgreSQL is required for parts of the test suite.
- Schema changes require Alembic migrations and a checkpoint update.
- PostgreSQL remains the system of record if pgvector is adopted; it does not replace the database.
