"""Chave persistente do cofre no volume privado de HML (Linux).

Sem cache: cada acesso detecta perda/troca do arquivo. O lock cobre a consulta
à persistência e a publicação; nunca substituir uma chave já existente.
"""
import hashlib
import os
from pathlib import Path
import stat
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.persistence.database import DatabaseNotConfigured, session_scope
from app.persistence.models import Credential


class VaultFileUnavailable(Exception):
    """Contém somente mensagem pública controlada, sem paths ou dados de OS."""


def _database_key_ids():
    try:
        if not settings.database_url:
            raise DatabaseNotConfigured()
        with session_scope() as session:
            # Inclui arquivadas: nenhuma evidência cifrada pode ser abandonada.
            return set(session.scalars(select(Credential.key_id).distinct()))
    except (DatabaseNotConfigured, SQLAlchemyError):
        raise VaultFileUnavailable(
            'Não foi possível verificar as credenciais existentes; inicialização do cofre interrompida.'
        ) from None


def _check_private(fd, directory=False):
    info = os.fstat(fd)
    expected = 0o700 if directory else 0o600
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not correct_type or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != expected
            or (not directory and info.st_nlink != 1)):
        raise VaultFileUnavailable('Armazenamento do cofre sem permissões seguras; operação interrompida.')


def _private_directory(path):
    """Percorre por descritores sem seguir links, incluindo os ancestrais."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = path.parts[1:]
        for index, component in enumerate(parts):
            created = False
            try:
                os.mkdir(component, mode=0o700, dir_fd=fd)
                created = True
            except FileExistsError:
                pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                # Persistir também a entrada do diretório privado no volume.
                if created or index == len(parts) - 1:
                    os.fsync(fd)
            except BaseException:
                os.close(child)
                raise
            os.close(fd)
            fd = child
        _check_private(fd, directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_key(directory, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        _check_private(fd)
        if os.fstat(fd).st_size > 128:
            raise ValueError()
        key = os.read(fd, 129).decode('ascii').strip()
        if len(key) != 44 or key == settings.auth_session_key:
            raise ValueError()
        Fernet(key.encode('ascii'))
        return key
    except (ValueError, UnicodeError):
        raise VaultFileUnavailable('Arquivo da chave do cofre inválido; restaure a chave original.') from None
    finally:
        os.close(fd)


def _publish_key(directory, name, key):
    temporary = '.' + uuid4().hex + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            _check_private(stream.fileno())
            stream.write(key.encode('ascii') + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        # link é atômico e recusa destino existente; não sobrescreve como replace.
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory)
    os.fsync(directory)


def load_or_create_key(filename):
    if os.name != 'posix':
        raise VaultFileUnavailable('Cofre automático requer armazenamento Linux; use CREDENTIAL_KEYS nesta instalação.')
    import fcntl

    path = Path(filename)
    if not path.is_absolute() or '..' in path.parts or not path.name or path.name == '.init.lock':
        raise VaultFileUnavailable('Caminho privado do cofre inválido.')
    directory = None
    lock = None
    try:
        directory = _private_directory(path.parent)
        lock = os.open('.init.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=directory)
        _check_private(lock)
        fcntl.flock(lock, fcntl.LOCK_EX)
        key = _read_key(directory, path.name)
        existing = _database_key_ids()
        if key is None:
            if existing:
                raise VaultFileUnavailable('Chave do cofre ausente. Restaure a chave original antes de continuar.')
            key = Fernet.generate_key().decode('ascii')
            if key == settings.auth_session_key:
                raise VaultFileUnavailable('Não foi possível inicializar uma chave independente para o cofre.')
            _publish_key(directory, path.name, key)
        else:
            fingerprint = hashlib.sha256(key.encode('ascii')).hexdigest()[:16]
            if existing - {fingerprint}:
                raise VaultFileUnavailable('A chave persistida não corresponde às credenciais. Restaure a chave original.')
        return key
    except OSError:
        raise VaultFileUnavailable('Não foi possível acessar o armazenamento privado do cofre.') from None
    finally:
        if lock is not None:
            # Fechar o descritor libera flock mesmo em erro ou término do processo.
            os.close(lock)
        if directory is not None:
            os.close(directory)
