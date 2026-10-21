"""Auditoria transacional: apenas metadados explícitos, nunca bodies ou segredos."""
from app.persistence.models import AuditEvent


def record(session, operation, outcome, actor_id=None, target=None):
    session.add(AuditEvent(actor_id=actor_id, operation=operation, outcome=outcome,
                           target=str(target)[:160] if target is not None else None))
