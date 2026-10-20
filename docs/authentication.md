# Autenticação simplificada

A autenticação é ativada explicitamente com `AUTH_ENABLED=true`. O padrão é
`false` para permitir a transição sem interromper os diagnósticos legados.
Quando ativada, `/`, `/analise/*`, `/monitor/*` e os endpoints administrativos
exigem sessão válida; `/health`, `/static/*` e `/auth/login` permanecem públicos.
Indisponibilidade do banco retorna erro controlado e nunca libera acesso anônimo.

## Configuração

Defina fora do Git:

```text
AUTH_ENABLED=true
AUTH_SESSION_KEY=<chave Fernet base64-url-safe de 32 bytes>
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
```

Em homologação HTTP interna, `AUTH_COOKIE_SECURE=false` só deve ser definido
explicitamente. HTTP não protege o cookie contra interceptação; HTTPS com
`Secure=true` é obrigatório para produção.

## Primeiro administrador

Depois de provisionar o banco e aplicar a migration aprovada, execute no
container/aplicação com `DATABASE_URL` configurada:

```bash
python -m app.admin create-admin administrador
```

O comando solicita a senha duas vezes, exige no mínimo 12 caracteres e não usa
senha padrão. A chave `AUTH_SESSION_KEY` deve estar disponível quando a
aplicação for ativada.

## Sessões e revogação

O cookie HttpOnly persistente dura 30 dias e é renovado quando restam menos de
7 dias. Ele contém uma credencial Fernet com expiração, identificador de usuário
e `auth_version`. Logout remove os cookies. Alteração de senha, desativação e
revogação incrementam `auth_version` e invalidam todas as sessões do usuário.

Permissões ficam no JSONB de `users` e são negadas por padrão; cada verificação
é feita no backend. CSRF usa um token derivado criptograficamente do cookie de
sessão e valida `Origin` quando presente.
