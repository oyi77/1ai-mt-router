"""add missing tables, columns, indexes, and constraints

Revision ID: 002
Revises: 001
Create Date: 2024-01-01 00:00:01.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- mt5_accounts: columns present in the model but missing from 001 ----
    op.add_column(
        "mt5_accounts",
        sa.Column("connection_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "mt5_accounts",
        sa.Column("connection_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "mt5_accounts",
        sa.Column("last_disconnected", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "mt5_accounts",
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # ---- users.two_factor_secret: widen to Text (SQLite needs batch mode) ----
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "two_factor_secret",
            existing_type=sa.String(length=32),
            type_=sa.Text(),
            existing_nullable=True,
            nullable=True,
        )

    # ---- subscriptions.user_id: enforce model's unique=True ----
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_subscriptions_user_id", ["user_id"]
        )

    # ---- new tables (models have index=True on id) ----
    op.create_table(
        "copy_strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_account_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("symbol_filter", sa.Text(), nullable=True),
        sa.Column("max_lots", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_account_id"],
            ["mt5_accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_copy_strategies_id"), "copy_strategies", ["id"], unique=False
    )

    op.create_table(
        "copy_subscribers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("target_account_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("lot_multiplier", sa.Float(), nullable=True),
        sa.Column("lot_type", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["copy_strategies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_account_id"],
            ["mt5_accounts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_copy_subscribers_id"), "copy_subscribers", ["id"], unique=False
    )

    op.create_table(
        "copy_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("ticket", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=50), nullable=True),
        sa.Column("order_type", sa.String(length=20), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("sl", sa.Float(), nullable=True),
        sa.Column("tp", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["copy_strategies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_copy_signals_id"), "copy_signals", ["id"], unique=False
    )

    op.create_table(
        "copy_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscriber_id", sa.Integer(), nullable=True),
        sa.Column("provider_ticket", sa.Integer(), nullable=True),
        sa.Column("subscriber_ticket", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=50), nullable=True),
        sa.Column("order_type", sa.String(length=20), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subscriber_id"],
            ["copy_subscribers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_copy_positions_id"), "copy_positions", ["id"], unique=False
    )

    op.create_table(
        "instance_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.String(length=100), nullable=False),
        sa.Column("instance_name", sa.String(length=255), nullable=True),
        sa.Column("cpu_percent", sa.Float(), nullable=True),
        sa.Column("memory_usage_mb", sa.Float(), nullable=True),
        sa.Column("memory_limit_mb", sa.Float(), nullable=True),
        sa.Column("memory_percent", sa.Float(), nullable=True),
        sa.Column("network_rx_mb", sa.Float(), nullable=True),
        sa.Column("network_tx_mb", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_instance_metrics_id"), "instance_metrics", ["id"], unique=False
    )

    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=255), nullable=True),
        sa.Column("events", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_webhook_configs_id"), "webhook_configs", ["id"], unique=False
    )

    # ---- indexes for index=True columns missing from 001 ----
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_instances_user_id"), "instances", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_instances_server_id"), "instances", ["server_id"], unique=False
    )
    op.create_index(
        op.f("ix_mt5_accounts_user_id"), "mt5_accounts", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_mt5_accounts_instance_id"),
        "mt5_accounts",
        ["instance_id"],
        unique=False,
    )
    op.create_index(op.f("ix_alerts_user_id"), "alerts", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_alerts_instance_id"), "alerts", ["instance_id"], unique=False
    )
    op.create_index(
        op.f("ix_usage_records_user_id"),
        "usage_records",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_usage_records_api_key_id"),
        "usage_records",
        ["api_key_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ssh_servers_user_id"), "ssh_servers", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_server_metrics_server_id"),
        "server_metrics",
        ["server_id"],
        unique=False,
    )
    op.create_index(op.f("ix_invoices_user_id"), "invoices", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_copy_strategies_user_id"),
        "copy_strategies",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_copy_strategies_source_account_id"),
        "copy_strategies",
        ["source_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_copy_subscribers_user_id"),
        "copy_subscribers",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_copy_subscribers_strategy_id"),
        "copy_subscribers",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_copy_subscribers_target_account_id"),
        "copy_subscribers",
        ["target_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_copy_signals_strategy_id"),
        "copy_signals",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_copy_positions_subscriber_id"),
        "copy_positions",
        ["subscriber_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_configs_user_id"),
        "webhook_configs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_instance_metrics_instance_id"),
        "instance_metrics",
        ["instance_id"],
        unique=False,
    )


def downgrade() -> None:
    # ---- indexes for index=True columns added in 002 ----
    op.drop_index(
        op.f("ix_instance_metrics_instance_id"), table_name="instance_metrics"
    )
    op.drop_index(
        op.f("ix_webhook_configs_user_id"), table_name="webhook_configs"
    )
    op.drop_index(
        op.f("ix_copy_positions_subscriber_id"), table_name="copy_positions"
    )
    op.drop_index(
        op.f("ix_copy_signals_strategy_id"), table_name="copy_signals"
    )
    op.drop_index(
        op.f("ix_copy_subscribers_target_account_id"),
        table_name="copy_subscribers",
    )
    op.drop_index(
        op.f("ix_copy_subscribers_strategy_id"), table_name="copy_subscribers"
    )
    op.drop_index(
        op.f("ix_copy_subscribers_user_id"), table_name="copy_subscribers"
    )
    op.drop_index(
        op.f("ix_copy_strategies_source_account_id"),
        table_name="copy_strategies",
    )
    op.drop_index(
        op.f("ix_copy_strategies_user_id"), table_name="copy_strategies"
    )
    op.drop_index(op.f("ix_invoices_user_id"), table_name="invoices")
    op.drop_index(
        op.f("ix_server_metrics_server_id"), table_name="server_metrics"
    )
    op.drop_index(
        op.f("ix_ssh_servers_user_id"), table_name="ssh_servers"
    )
    op.drop_index(
        op.f("ix_usage_records_api_key_id"), table_name="usage_records"
    )
    op.drop_index(op.f("ix_usage_records_user_id"), table_name="usage_records")
    op.drop_index(op.f("ix_alerts_instance_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_user_id"), table_name="alerts")
    op.drop_index(
        op.f("ix_mt5_accounts_instance_id"), table_name="mt5_accounts"
    )
    op.drop_index(op.f("ix_mt5_accounts_user_id"), table_name="mt5_accounts")
    op.drop_index(
        op.f("ix_instances_server_id"), table_name="instances"
    )
    op.drop_index(op.f("ix_instances_user_id"), table_name="instances")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")

    # ---- new tables (reverse creation order) ----
    op.drop_table("webhook_configs")
    op.drop_table("instance_metrics")
    op.drop_table("copy_positions")
    op.drop_table("copy_signals")
    op.drop_table("copy_subscribers")
    op.drop_table("copy_strategies")

    # ---- subscriptions.user_id unique constraint ----
    with op.batch_alter_table("subscriptions") as batch_op:
        batch_op.drop_constraint("uq_subscriptions_user_id", type_="unique")

    # ---- users.two_factor_secret back to String(32) ----
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "two_factor_secret",
            existing_type=sa.Text(),
            type_=sa.String(length=32),
            existing_nullable=True,
            nullable=True,
        )

    # ---- mt5_accounts columns added in 002 ----
    op.drop_column("mt5_accounts", "updated_at")
    op.drop_column("mt5_accounts", "last_disconnected")
    op.drop_column("mt5_accounts", "connection_error")
    op.drop_column("mt5_accounts", "connection_status")
