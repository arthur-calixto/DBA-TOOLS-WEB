# Planejamento — persistência, migrations e deploy futuro em produção

Documento de planejamento. Nenhum comando/pipeline/Compose de produção é
alterado ou executado nesta entrega. HML funcionando não comprova infraestrutura
igual em produção. Não promover código que exige tabelas novas só por copiar o
procedimento HML.

## Inventário obrigatório antes da aprovação

| Item | Evidência disponível / validação necessária |
|---|---|
| Aplicação | Contexto informa analise-ambiente, HTTP 8590. Confirmar VM, projeto Compose, digest/SHA e versão realmente em execução |
| Deploy | Repositório tem deploy.yml manual/SemVer e scripts/deploy.sh. Conferir variáveis, environment, runner e permissões reais |
| PostgreSQL | Existência NÃO confirmada. compose.persistence.production.yml é uma proposta, não prova de provisionamento |
| Banco/schema | Confirmar versão, endereço, bancos, owners, usuários/privilégios, Alembic current e extensões; sem imprimir URLs/senhas |
| Persistência | Inventariar diretórios/volumes, ownership, espaço, rede, backup/restore e responsáveis |
| Identidade | Confirmar AUTH_ENABLED, gestão/recuperação da chave, usuários/admin, roles/escopos, HTTPS, sessão atual |
| Dados JSON | Inventariar cadastros e origem, compartilhamento real entre ambientes, permissões e plano para separação; não copiar para HML |

Registrar inventário de modo sanitizado no Linear e obter validação do responsável
pela infraestrutura. Não assumir que volumes, bancos, chaves, credenciais ou
administrador existentes em HML possam ser usados em produção.

## Provisionamento se PostgreSQL não existir

Aprovar versão suportada, atualizações, capacidade e isolamento; projetar rede
privada de produção, serviço/volume próprio, sem publicar 5432 e sem rede HML.
Definir usuários de aplicação/migration/backup com privilégios necessários e
segredos independentes fora do Git. Preparar diretórios e permissões, política
de reinicialização, healthcheck e monitoramento. Testar conexão somente sob
aprovação, por conta e ambiente autorizados. A automação HML não provisiona isso.

## Dados e credenciais

Nesta etapa os JSONs permanecem a fonte operacional. Migração de clientes,
ambientes e credenciais é projeto separado: mapear campos/identidades, validar
ambiente, criptografia autenticada de segredos/chave fora do banco, planejar
importação idempotente e reconciliar contagens sem imprimir dados. Obter
aprovação para cópia, ensaio e cutover. Não transportar hashes/tokens/segredos de
HML para produção. Não executar import automaticamente junto de schema.

## Compatibilidade e bootstrap

Listar revisions necessárias do digest candidato, schema atual e riscos de cada
migration. Priorizar expand/contract e compatibilidade com a aplicação anterior
enquanto estiver servindo. Testar no ensaio de produção com dados autorizados.
Planejar novo login para sessões antigas e atribuição de perfis/escopos.
Após schema aprovado, criar primeiro administrador por comando seguro com prompt
(sem senha padrão) apenas se não existir. Gerenciar chave estável e recuperação
fora da imagem/Git. Conferir HTTPS/Secure, CSRF e acesso negado por padrão antes
de habilitar autenticação. Não expor aplicação sem login para contornar falhas.

## Backup e restauração

Definir RPO/RTO, retenção, criptografia, cópia fora da VM e acesso aos backups.
Ensaiar pg_dump/pg_restore em instância isolada, confirmar versão e privilégios,
integridade, usuários, sessões e auditoria. Medir tempo/espaço. Dump no mesmo
host, checksum e leitura de arquivo não substituem restore testado.
Registrar ponto de recuperação e destino seguro antes de migrations.

## Aprovação e janela

Exigir aprovação manual do responsável de banco/infraestrutura e aplicação,
janela de manutenção, comunicação, backup verificado, evidência de testes e
compatibilidade, digest imutável, SQL revisado e plano de recuperação. Projetar
concorrência exclusiva de produção e lock de migrations, sem reutilizar ambiente
ou locks operacionais HML. Somente numa tarefa futura aprovada alterar deploy.yml
ou Compose de produção. Não configurar Rulesets nesta tarefa.

## Rollback

Registrar digest anterior/configuração e schema compatível. Rollback somente da
aplicação se compatível; schema não sofre downgrade automático. Preferir correção
para frente. Se restauração do banco for necessária, interromper gravações sob
janela aprovada, contabilizar perda desde o backup, testar restore isolado e só
então autorizar troca. Considerar revogação de sessões, chave, auditoria e
reconciliação de cadastros. Não voltar a código sem RBAC/revogação preservando
cookies antigos. Validar rotas, login, permissões, PDF e Monitor antes de encerrar
a janela, com supervisão e procedimento de retorno definidos.
