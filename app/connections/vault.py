"""Cifra autenticada vinculada ao ID da credencial; nenhuma chave no banco."""
import hashlib
import json
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from app.errors import PublicHTTPException as HTTPException
from app.config import settings
from app.connections.key_file import VaultFileUnavailable, load_or_create_key


def keyring():
    try:
        if settings.credential_keys and settings.credential_keys.strip():
            # Chave explícita não vazia tem prioridade; inválida não aciona fallback.
            keys = [key.strip() for key in settings.credential_keys.split(',') if key.strip()]
        elif settings.credential_key_file:
            keys = [load_or_create_key(settings.credential_key_file)]
        else:
            keys = []
        if not keys or settings.auth_session_key in keys:
            raise ValueError()
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys]), hashlib.sha256(keys[0].encode()).hexdigest()[:16]
    except VaultFileUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(503, 'Cofre indisponível.') from None


def seal(identifier, username, password):
    cipher, key_id = keyring()
    payload = {'id': identifier, 'username': username, 'password': password}
    return cipher.encrypt(json.dumps(payload).encode()).decode(), key_id


def unseal(credential):
    try:
        cipher, _ = keyring()
        data = json.loads(cipher.decrypt(credential.ciphertext.encode()))
        if data.get('id') != credential.id:
            raise ValueError()
        return {'username': data['username'], 'password': data['password']}
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(503, 'Cofre indisponível.') from None
