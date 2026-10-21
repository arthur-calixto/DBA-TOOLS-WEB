"""Matriz explícita e escopos, independentes da interface."""
ACTIONS = {'diagnostics.view', 'diagnostics.execute', 'monitor.view', 'monitor.execute', 'reports.export'}
ROLES = {
    'leitura': {'diagnostics.view', 'monitor.view', 'reports.export'},
    'analista': ACTIONS,
    'dba': ACTIONS,
}


def valid_policy(role, permissions, scopes):
    return (role in ROLES and isinstance(permissions, dict)
            and all(key in ACTIONS and type(value) is bool for key, value in permissions.items())
            and isinstance(scopes, dict)
            and all(isinstance(key, str) and 0 < len(key) <= 80
                    and isinstance(values, list) and values
                    and all(isinstance(value, str) and 0 < len(value) <= 80 for value in values)
                    for key, values in scopes.items()))


def allowed(user, action):
    if user.is_admin:
        return True
    if not valid_policy(user.role, user.permissions, user.access_scopes):
        return False
    return user.permissions.get(action, action in ROLES[user.role]) is True


def scoped(user, client, environment=None):
    if user.is_admin:
        return True
    if not valid_policy(user.role, user.permissions, user.access_scopes):
        return False
    values = user.access_scopes.get(client, []) + user.access_scopes.get('*', [])
    return bool(values) if environment is None else environment in values or '*' in values
