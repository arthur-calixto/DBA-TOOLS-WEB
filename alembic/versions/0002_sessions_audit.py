"""Persist sessions, role/scopes and audit trail.

Revision ID: 0002_sessions_audit
Revises: 0001_users
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002_sessions_audit'
down_revision = '0001_users'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('role', sa.String(20), nullable=False, server_default='leitura'))
    op.add_column('users', sa.Column('access_scopes', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.create_table('auth_sessions',
                    sa.Column('id_hash', sa.String(64), primary_key=True),
                    sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
                    sa.Column('auth_version', sa.Integer(), nullable=False),
                    sa.Column('created_at', sa.BigInteger(), nullable=False),
                    sa.Column('expires_at', sa.BigInteger(), nullable=False),
                    sa.Column('revoked_at', sa.BigInteger()))
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_index('ix_auth_sessions_expires_at', 'auth_sessions', ['expires_at'])
    op.create_table('audit_events',
                    sa.Column('id', sa.Integer(), primary_key=True),
                    sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id')),
                    sa.Column('operation', sa.String(80), nullable=False),
                    sa.Column('outcome', sa.String(20), nullable=False),
                    sa.Column('target', sa.String(160)),
                    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_audit_events_actor_id', 'audit_events', ['actor_id'])
    op.create_index('ix_audit_events_occurred_at', 'audit_events', ['occurred_at'])


def downgrade():
    op.drop_table('audit_events')
    op.drop_table('auth_sessions')
    op.drop_column('users', 'access_scopes')
    op.drop_column('users', 'role')
