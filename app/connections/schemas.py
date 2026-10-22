"""Payloads tipados; parâmetros de conexão são uma allowlist, nunca comandos."""
import ipaddress
import re
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictStr, field_validator, model_validator

ConnectionType = Literal['oracle', 'sqlserver', 'postgresql', 'ssh', 'rdp', 'sftp', 'scp']
PARAMETERS = {
    'oracle': {'service_name', 'sid', 'tns_alias'},
    'sqlserver': {'database', 'instance', 'encrypt', 'trust_server_certificate'},
    'postgresql': {'database', 'sslmode'},
    'ssh': {'host_key_fingerprint'}, 'sftp': {'host_key_fingerprint', 'initial_directory'},
    'scp': {'host_key_fingerprint', 'initial_directory'}, 'rdp': {'domain'},
}


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)

    @field_validator('name', check_fields=False)
    @classmethod
    def clean_name(cls, value):
        value = unicodedata.normalize("NFC", value.strip())
        if not value or len(value.casefold()) > 160 or any(ord(c) < 32 for c in value):
            raise ValueError('Nome inválido')
        return value


class ClientInput(Payload):
    name: str = Field(min_length=1, max_length=160)
    legacy_key: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator('legacy_key')
    @classmethod
    def legacy(cls, value):
        if value is not None:
            from app.session import _validate_cliente_id
            try:
                _validate_cliente_id(value)
            except Exception:
                raise ValueError('Identificador legado inválido') from None
        return value


class EnvironmentInput(Payload):
    name: str = Field(min_length=1, max_length=160)
    system: str = Field(default='', max_length=160)
    internal_address: str = Field(default='', max_length=255)
    external_address: str = Field(default='', max_length=255)
    contacts: str = Field(default='', max_length=4000)


class ConnectionInput(Payload):
    name: str = Field(min_length=1, max_length=160)
    type: ConnectionType
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(strict=True, ge=1, le=65535)
    credential_id: UUID
    parameters: dict[str, StrictStr | StrictBool] = Field(default_factory=dict)
    notes: str = Field(default='', max_length=4000)

    @field_validator('host')
    @classmethod
    def valid_host(cls, value):
        value = value.strip()
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,253}[A-Za-z0-9])?', value):
                raise ValueError('Host inválido') from None
            if any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
                   for label in value.split('.')):
                raise ValueError('Host inválido') from None
        return value

    @model_validator(mode='after')
    def valid_parameters(self):
        if self.parameters.keys() - PARAMETERS[self.type]:
            raise ValueError('Parâmetros não suportados')
        for key, value in self.parameters.items():
            if key in {'encrypt', 'trust_server_certificate'}:
                if type(value) is not bool:
                    raise ValueError('Booleano obrigatório')
            elif not isinstance(value, str) or len(value) > 512 or any(ord(c) < 32 for c in value):
                raise ValueError('Parâmetro inválido')
        if self.type == 'oracle' and sum(bool(self.parameters.get(k)) for k in PARAMETERS['oracle']) != 1:
            raise ValueError('Informe exatamente um serviço, SID ou alias TNS')
        if self.type == 'postgresql' and self.parameters.get('sslmode', 'require') not in {
                'disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'}:
            raise ValueError('SSL mode inválido')
        return self


class CredentialInput(Payload):
    name: str = Field(min_length=1, max_length=160)
    username: SecretStr = Field(min_length=1, max_length=512)
    password: SecretStr = Field(min_length=1, max_length=8192)


class ClientUpdate(ClientInput):
    version: int = Field(gt=0)


class EnvironmentUpdate(EnvironmentInput):
    version: int = Field(gt=0)


class ConnectionUpdate(ConnectionInput):
    version: int = Field(gt=0)


class CredentialUpdate(Payload):
    name: str = Field(min_length=1, max_length=160)
    username: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=8192)
    version: int = Field(gt=0)
    confirm_shared: bool = False


class ConnectionCreate(ConnectionInput):
    """Cadastro completo, mantendo os contratos das APIs avançadas existentes."""
    credential_id: UUID | None = None
    client_id: UUID | None = None
    client_name: str | None = Field(default=None, min_length=1, max_length=160)
    environment_id: UUID | None = None
    environment_name: str | None = Field(default=None, min_length=1, max_length=160)
    username: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=8192)

    @field_validator('client_name', 'environment_name')
    @classmethod
    def selection_name(cls, value):
        return Payload.clean_name(value) if value is not None else None

    @model_validator(mode='after')
    def selections(self):
        if bool(self.client_id) == bool(self.client_name):
            raise ValueError('Selecione ou informe um cliente')
        if bool(self.environment_id) == bool(self.environment_name):
            raise ValueError('Selecione ou informe um ambiente')
        inline = self.username is not None or self.password is not None
        if (self.credential_id and inline) or (not self.credential_id and not (self.username and self.password)):
            raise ValueError('Selecione uma credencial ou informe usuário e senha')
        return self
