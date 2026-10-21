"""Cadastros e cofre compartilhado; não importa nem altera JSONs.

Revision ID: 0003_connections
Revises: 0002_sessions_audit
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0003_connections'
down_revision = '0002_sessions_audit'
branch_labels = None
depends_on = None


def common():
    return [sa.Column('id', sa.Uuid(as_uuid=False), primary_key=True),
            sa.Column('name', sa.String(160), nullable=False),
            sa.Column('normalized_name', sa.String(160), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('updated_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table('clients', *common(), sa.Column('legacy_key', sa.String(80)),
                    sa.UniqueConstraint('legacy_key'), sa.UniqueConstraint('normalized_name'))
    op.create_table('environments', *common(),
                    sa.Column('client_id', sa.Uuid(as_uuid=False), sa.ForeignKey('clients.id'), nullable=False),
                    sa.Column('system', sa.String(160), nullable=False),
                    sa.Column('internal_address', sa.String(255), nullable=False),
                    sa.Column('external_address', sa.String(255), nullable=False),
                    sa.Column('contacts', sa.Text(), nullable=False),
                    sa.UniqueConstraint('client_id', 'normalized_name'))
    op.create_index('ix_environments_client_id', 'environments', ['client_id'])
    op.create_table('credentials', *common(), sa.Column('ciphertext', sa.Text(), nullable=False),
                    sa.Column('key_id', sa.String(16), nullable=False), sa.UniqueConstraint('normalized_name'))
    op.create_table('connections', *common(),
                    sa.Column('environment_id', sa.Uuid(as_uuid=False), sa.ForeignKey('environments.id'), nullable=False),
                    sa.Column('credential_id', sa.Uuid(as_uuid=False), sa.ForeignKey('credentials.id'), nullable=False),
                    sa.Column('type', sa.String(20), nullable=False), sa.Column('host', sa.String(255), nullable=False),
                    sa.Column('port', sa.Integer(), nullable=False), sa.Column('parameters', JSONB(), nullable=False),
                    sa.Column('notes', sa.Text(), nullable=False), sa.UniqueConstraint('environment_id', 'normalized_name'),
                    sa.CheckConstraint('port >= 1 AND port <= 65535', name='ck_connections_port'),
                    sa.CheckConstraint("type IN ('oracle','sqlserver','postgresql','ssh','rdp','sftp','scp')", name='ck_connections_type'))
    op.create_index('ix_connections_environment_id', 'connections', ['environment_id'])
    op.create_index('ix_connections_credential_id', 'connections', ['credential_id'])


def downgrade():
    # Somente comando manual explícito; deploy não executa downgrade automático.
    for table in ('connections', 'credentials', 'environments', 'clients'):
        op.drop_table(table)
