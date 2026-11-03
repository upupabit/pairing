"""MySQL: every DATETIME column keeps microseconds (DATETIME(6))

Plain DATETIME keeps whole seconds, so a message and its reply created in the same second tied and showed in
either order. SQLite already keeps microseconds, so it is left as it is.

Revision ID: f6c2e8a4b1d7
Revises: e4b8d1f3a6c9
"""

import sqlalchemy as sa

from alembic import op

revision = "f6c2e8a4b1d7"
down_revision = "e4b8d1f3a6c9"
branch_labels = None
depends_on = None


def _datetime_columns(precision: int) -> list[tuple[str, str, bool]]:
    rows = op.get_bind().execute(
        sa.text(
            "SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND DATA_TYPE = 'datetime' AND DATETIME_PRECISION = :p"
        ),
        {"p": precision},
    )
    return [(table, column, nullable == "YES") for table, column, nullable in rows]


def _convert(from_precision: int, to_type: str) -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    for table, column, nullable in _datetime_columns(from_precision):
        op.execute(f"ALTER TABLE `{table}` MODIFY `{column}` {to_type} {'NULL' if nullable else 'NOT NULL'}")


def upgrade() -> None:
    _convert(0, "DATETIME(6)")


def downgrade() -> None:
    _convert(6, "DATETIME")
