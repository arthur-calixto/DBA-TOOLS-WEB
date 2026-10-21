# Monitor: processamento e homologação (TER-9)

A versão anterior ao hardening (`dfef44f^`) lia ZIP e log completos na memória.
O hardening `dfef44f` adicionou tetos para corpo HTTP, upload, entradas,
descompressão, razão, log, registros e tempo. Aumentar a descompressão de
32 para 256 MiB não removia os bloqueios seguintes (log de 8 MiB, 50 mil
blocos, 15 segundos).

O Monitor não aplica mais esses tetos. As respectivas configurações antigas
continuam disponíveis para compatibilidade, mas não limitam esse fluxo.
Os limites de relatórios e das outras funcionalidades continuam ativos.

O corpo HTTP usa spool em arquivo temporário; o log selecionado é descompactado
em leituras de 64 KiB e interpretado registro por registro. Apenas esse log é
descompactado. Agregações por processo e ranking ficam em SQLite temporário,
com cache de 2 MiB e temporários em disco. O resultado mantém os 30 primeiros
processos/consultas, como na versão original; contagem e tempo incluem todos
os registros. SQL completo das consultas selecionadas continua disponível.
Nenhum banco PostgreSQL ou cadastro JSON é alterado.

Permanecem validações do diretório ZIP, contagem declarada versus headers,
CRC do log lido, caminhos, links, criptografia, métodos de compressão e
exigência de exatamente um Monitor_Consulta.log. Nada é extraído para caminhos
fornecidos pelo arquivo. ZIP64 passa pela validação da biblioteca zipfile.
O semáforo `MONITOR_MAX_CONCURRENT` mantém isolamento de concorrência; sem vaga,
o processamento retorna 429. Falhas de disco/memória geram erro genérico com
referência, e os temporários são fechados/removidos inclusive em falhas.

Sem limites de bytes/tempo, um log de alta compressão ainda pode ocupar um
worker por muito tempo. O semáforo limita concorrência, não CPU ou duração.
A memória acompanha o maior registro individual (inclusive seu SQL), os
metadados de entradas mantidos por zipfile e os resultados retornados; não
há promessa de memória constante ou upload fisicamente ilimitado. O parser
não mantém o log ou a coleção completa de registros. Recursos reais de
memória, disco e eventuais timeouts do servidor/proxy continuam aplicáveis.
Não há mudança de infraestrutura nesta correção.

## Validação pendente em homologação

O ZIP real não está disponível no desenvolvimento. O SHA implantado e a
mensagem atual devem ser conferidos no resumo do deploy manual (digest) e no
Network do navegador antes de atribuir uma falha a essa versão. Não registrar
cookies, tokens nem conteúdo do log na issue.

Após deploy manual aprovado: fazer login, enviar o mesmo ZIP, conferir total,
tempo, ranking e cópia de SQL; validar PDF/Análise de Ambiente e logout.
Registrar SHA/digest, tamanho ZIP, soma descompactada e número de entradas
(apenas metadados), resultado e consumo observado. TER-9 permanece In Progress
até esse arquivo funcionar em HML. Nenhum deploy é disparado pela correção.

## Suíte permanente — TER-2 / Etapa 2.4

`tests/test_monitor.py` preserva ZIP inválido, traversal, CRC, concorrência,
limite de relatório e uploads acima do antigo limite HTTP. Fixtures são
sintéticas: nenhum log de cliente é versionado.

`tests/test_monitor_streaming.py` cobre individualmente os seis antigos tetos
com configurações reduzidas e relógio virtual, sem sleeps: entradas,
descompressão, razão, log, registros e prazo. Também cobre login real do
endpoint com PostgreSQL simulado, cookie/sessão criptográfica, CSRF válido,
inválido/ausente, upload de 12 MiB e resultado. Testes com dados reais em volume
sintético cobrem log de 257 MiB, mais de 200 entradas e 50.001 registros.
Spool e diretório/SQLite temporários são verificados após sucesso e falha.

Execute `python -m unittest discover -s tests -v` e depois
`python scripts/check-monitor-mutations.py`. O segundo comando cria cópias
privadas temporárias de app/tests, confirma baseline verde e reintroduz cada
bloqueio isoladamente: os seis testes devem falhar por AssertionError. A árvore
de trabalho não é modificada. Uma baseline quebrada, timeout, erro de import ou
mutante não detectado reprova a verificação.

`.github/workflows/tests.yml` executa esses comandos automaticamente em PR e
push na develop, com timeout de job (não do processamento da aplicação).
Não há continue-on-error nem skips. Os cenários de volume levam poucos segundos
localmente, com geração em blocos e sem esperas, portanto continuam na suíte
principal. Se crescerem, separar em job obrigatório, nunca torná-los opcionais.
O workflow manual de HML já descobre esses testes antes do build/publicação.
O workflow de produção permanece inalterado.

Para impedir merge com CI vermelho, configurar `Regression tests / regression`
como check obrigatório na proteção/ruleset da branch. O YAML sozinho não cria
essa política do GitHub. Não houve alteração de rulesets nesta implementação.
