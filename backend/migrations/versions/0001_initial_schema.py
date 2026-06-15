"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batches_status", "batches", ["status"])

    op.create_table(
        "cases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("application_fields", sa.JSON(), nullable=False),
        sa.Column("image_sha256", sa.String(), nullable=False),
        sa.Column("image_path", sa.String(), nullable=False),
        sa.Column("current_recommendation", sa.String(), nullable=True),
        sa.Column("final_decision", sa.String(), nullable=True),
        sa.Column("final_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_image_sha256", "cases", ["image_sha256"])
    op.create_index("ix_cases_status", "cases", ["status"])

    op.create_table(
        "tier_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("layer", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tier_events_case_id", "tier_events", ["case_id"])
    op.create_index("ix_tier_events_layer", "tier_events", ["layer"])

    op.create_table(
        "field_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("expected_value", sa.Text(), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_layer", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_results_case_id", "field_results", ["case_id"])
    op.create_index("ix_field_results_field_name", "field_results", ["field_name"])

    op.create_table(
        "provider_usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("base_url_label", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_usage_case_id", "provider_usage", ["case_id"])

    op.create_table(
        "human_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer_label", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_human_decisions_case_id", "human_decisions", ["case_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_batch_id", "audit_events", ["batch_id"])
    op.create_index("ix_audit_events_case_id", "audit_events", ["case_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    op.create_table(
        "verification_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_jobs_batch_id", "verification_jobs", ["batch_id"])
    op.create_index("ix_verification_jobs_case_id", "verification_jobs", ["case_id"])
    op.create_index("ix_verification_jobs_status", "verification_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_verification_jobs_status", table_name="verification_jobs")
    op.drop_index("ix_verification_jobs_case_id", table_name="verification_jobs")
    op.drop_index("ix_verification_jobs_batch_id", table_name="verification_jobs")
    op.drop_table("verification_jobs")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_case_id", table_name="audit_events")
    op.drop_index("ix_audit_events_batch_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_human_decisions_case_id", table_name="human_decisions")
    op.drop_table("human_decisions")
    op.drop_index("ix_provider_usage_case_id", table_name="provider_usage")
    op.drop_table("provider_usage")
    op.drop_index("ix_field_results_field_name", table_name="field_results")
    op.drop_index("ix_field_results_case_id", table_name="field_results")
    op.drop_table("field_results")
    op.drop_index("ix_tier_events_layer", table_name="tier_events")
    op.drop_index("ix_tier_events_case_id", table_name="tier_events")
    op.drop_table("tier_events")
    op.drop_index("ix_cases_status", table_name="cases")
    op.drop_index("ix_cases_image_sha256", table_name="cases")
    op.drop_table("cases")
    op.drop_index("ix_batches_status", table_name="batches")
    op.drop_table("batches")
