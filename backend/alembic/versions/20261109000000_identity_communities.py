"""Identity, community and agent records.

Revision ID: 20261109000000
Revises: 20240101000000
Create Date: 2026-11-09
"""

from alembic import op
import sqlalchemy as sa

from app.db.types import PointGeometry

revision = "20261109000000"
down_revision = "20240101000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    uses_postgis = bind.dialect.name == "postgresql"
    if uses_postgis:
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    point_type = PointGeometry() if uses_postgis else sa.String()

    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("preferred_language", sa.String(length=12), nullable=False, server_default="en"),
    )
    op.drop_index("ix_users_phone", table_name="users")
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)

    op.create_table(
        "phone_verifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("code_digest", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "communities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("community_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="NG"),
        sa.Column("area", sa.String(length=160), nullable=True),
        sa.Column("creator_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_communities_name", "communities", ["name"], unique=False)
    op.create_index("ix_communities_creator_id", "communities", ["creator_id"], unique=False)

    op.create_table(
        "community_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("community_id", sa.String(length=36), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("community_id", "user_id", name="uq_community_membership"),
    )
    op.create_index("ix_community_memberships_community_id", "community_memberships", ["community_id"], unique=False)
    op.create_index("ix_community_memberships_user_id", "community_memberships", ["user_id"], unique=False)

    op.create_table(
        "community_agents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("identity_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reviewed_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_community_agents_status", "community_agents", ["status"], unique=False)

    op.create_table(
        "addresses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("address_line", sa.String(length=255), nullable=False),
        sa.Column("area", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="NG"),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("location", point_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_addresses_user_id", "addresses", ["user_id"], unique=False)
    if uses_postgis:
        op.create_index("idx_addresses_location", "addresses", ["location"], postgresql_using="gist")

    op.create_table(
        "collection_points",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("community_id", sa.String(length=36), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("address_line", sa.String(length=255), nullable=False),
        sa.Column("operating_hours", sa.String(length=255), nullable=True),
        sa.Column("responsible_person", sa.String(length=160), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("location", point_type, nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_collection_points_community_id", "collection_points", ["community_id"], unique=False)
    if uses_postgis:
        op.create_index("idx_collection_points_location", "collection_points", ["location"], postgresql_using="gist")

    op.create_table(
        "agent_community_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("community_id", sa.String(length=36), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("agent_id", "community_id", name="uq_agent_community_assignment"),
    )
    op.create_index("ix_agent_community_assignments_agent_id", "agent_community_assignments", ["agent_id"], unique=False)
    op.create_index("ix_agent_community_assignments_community_id", "agent_community_assignments", ["community_id"], unique=False)

    op.create_table(
        "agent_consents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("member_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_agent_consents_member_id", "agent_consents", ["member_id"], unique=False)
    op.create_index("ix_agent_consents_agent_id", "agent_consents", ["agent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_consents_agent_id", table_name="agent_consents")
    op.drop_index("ix_agent_consents_member_id", table_name="agent_consents")
    op.drop_table("agent_consents")
    op.drop_index("ix_agent_community_assignments_community_id", table_name="agent_community_assignments")
    op.drop_index("ix_agent_community_assignments_agent_id", table_name="agent_community_assignments")
    op.drop_table("agent_community_assignments")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("idx_collection_points_location", table_name="collection_points")
    op.drop_index("ix_collection_points_community_id", table_name="collection_points")
    op.drop_table("collection_points")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("idx_addresses_location", table_name="addresses")
    op.drop_index("ix_addresses_user_id", table_name="addresses")
    op.drop_table("addresses")
    op.drop_index("ix_community_agents_status", table_name="community_agents")
    op.drop_table("community_agents")
    op.drop_index("ix_community_memberships_user_id", table_name="community_memberships")
    op.drop_index("ix_community_memberships_community_id", table_name="community_memberships")
    op.drop_table("community_memberships")
    op.drop_index("ix_communities_creator_id", table_name="communities")
    op.drop_index("ix_communities_name", table_name="communities")
    op.drop_table("communities")
    op.drop_table("phone_verifications")
    op.drop_index("ix_users_phone", table_name="users")
    op.create_index("ix_users_phone", "users", ["phone"], unique=False)
    op.drop_column("users", "preferred_language")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "password_hash")
