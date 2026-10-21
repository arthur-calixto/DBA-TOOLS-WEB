"""Cifra autenticada vinculada ao ID da credencial; nenhuma chave no banco."""
import hashlib
import json
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from app.errors import PublicHTTPException as HTTPException
from app.config import settings


def keyring():
    try:
        keys = [key.strip() for key in (settings.credential_keys or '').split(',') if key.strip()]
        if not keys or settings.auth_session_key in keys:
            raise ValueError()
        return MultiFernet([Fernet(key.encode('ascii')) for key in keys]), hashlib.sha256(keys[0].encode()).hexdigest()[:16]
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
