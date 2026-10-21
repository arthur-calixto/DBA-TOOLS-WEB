/* Cadastro compartilhado. Somente textContent/DOM; sem HTML de dados externos. */
(() => {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const types = {
        oracle: 'Oracle',
        sqlserver: 'SQL Server',
        postgresql: 'PostgreSQL',
        ssh: 'Linux / SSH',
        rdp: 'Windows / RDP',
        sftp: 'SFTP',
        scp: 'SCP'
    };
    const state = {
        client: null,
        environments: [],
        credentials: [],
        next: null,
        clientLoad: 0,
        rowsLoad: 0
    };
    const status = (text) => {
        $('catalog-status').textContent = text;
    };
    const element = (tag, text) => {
        const e = document.createElement(tag);
        if (text !== undefined) e.textContent = text;
        return e;
    };
    function button(text, action) {
        const b = element('button', text);
        b.type = 'button';
        b.className = 'btn-secundario';
        b.addEventListener('click', () => safe(action));
        return b;
    }
    async function safe(action) {
        try {
            await action();
        } catch (error) {
            status(error.message || 'Não foi possível concluir a operação.');
        }
    }
    function csrf() {
        const value = document.cookie
            .split('; ')
            .find((v) => v.startsWith('dba_tools_csrf='));
        return value
            ? decodeURIComponent(value.slice('dba_tools_csrf='.length))
            : '';
    }
    async function api(path, method = 'GET', data) {
        const response = await fetch('/api' + path, {
            method,
            credentials: 'same-origin',
            cache: 'no-store',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': csrf()
            },
            body: data === undefined ? undefined : JSON.stringify(data)
        });
        let result = {};
        try {
            result = await response.json();
        } catch (_) {}
        if (!response.ok)
            throw new Error(
                result.erro || 'Não foi possível concluir a operação.'
            );
        return result;
    }
    async function all(path) {
        let items = [],
            next = 0;
        do {
            const data = await api(
                path + (path.includes('?') ? '&' : '?') + 'offset=' + next
            );
            items.push(...data.items);
            next = data.next_offset;
        } while (next !== null && next !== undefined);
        return items;
    }
    function panel(name) {
        for (const id of [
            'clients-panel',
            'connections-panel',
            'credentials-panel'
        ])
            $(id).hidden = id !== name;
    }
    function field(
        form,
        name,
        label,
        value = '',
        kind = 'text',
        required = false
    ) {
        const wrapper = element('label', label);
        let input;
        if (kind === 'textarea') {
            input = element('textarea');
            input.rows = 3;
        } else {
            input = element('input');
            input.type = kind;
        }
        input.name = name;
        input.value = kind === 'checkbox' ? 'true' : (value ?? '');
        input.required = required;
        input.autocomplete = kind === 'password' ? 'new-password' : 'off';
        wrapper.append(input);
        form.append(wrapper);
        return input;
    }
    function select(form, name, label, choices, value = '') {
        const wrapper = element('label', label),
            input = element('select');
        input.name = name;
        for (const [id, text] of choices) {
            const option = element('option', text);
            option.value = id;
            input.append(option);
        }
        input.value = value;
        input.required = true;
        wrapper.append(input);
        form.append(wrapper);
        return input;
    }
    function editor(title, build, save) {
        const dialog = $('editor'),
            form = $('catalog-form'),
            fields = $('editor-fields');
        fields.replaceChildren();
        $('save-catalog').hidden = false;
        $('editor-title').textContent = title;
        $('editor-error').hidden = true;
        build(fields);
        form.onsubmit = async (event) => {
            event.preventDefault();
            const submit = $('save-catalog');
            submit.disabled = true;
            try {
                await save(new FormData(form));
                dialog.close();
                fields.replaceChildren();
                status('Cadastro atualizado.');
            } catch (error) {
                $('editor-error').textContent = error.message;
                $('editor-error').hidden = false;
            } finally {
                submit.disabled = false;
            }
        };
        dialog.showModal();
    }
    const text = (data, name) => String(data.get(name) ?? '');
    async function clients() {
        panel('clients-panel');
        const items = await all(
            '/clients?q=' + encodeURIComponent($('client-search').value)
        );
        $('catalog-clients').replaceChildren(
            ...items.map((c) => {
                const b = button(c.name, () => openClient(c));
                b.classList.add('cliente-item');
                return b;
            })
        );
        if (!items.length)
            $('catalog-clients').textContent = 'Nenhum cliente encontrado.';
    }
    function editClient(row = null) {
        editor(
            row ? 'Editar cliente' : 'Novo cliente',
            (form) => {
                field(form, 'name', 'Nome', row?.name, 'text', true);
                field(
                    form,
                    'legacy_key',
                    'Identificador JSON existente (opcional; não importa dados)',
                    row?.legacy_key
                );
            },
            async (data) => {
                const result = await api(
                    '/clients' + (row ? '/' + row.id : ''),
                    row ? 'PATCH' : 'POST',
                    {
                        name: text(data, 'name'),
                        legacy_key: text(data, 'legacy_key') || null,
                        ...(row ? { version: row.version } : {})
                    }
                );
                await clients();
                if (row) await openClient(result);
            }
        );
    }
    async function openClient(client) {
        const generation = ++state.clientLoad;
        state.client = client;
        panel('connections-panel');
        $('connections-title').textContent =
            client.name + ' — todas as conexões';
        $('connection-rows').replaceChildren();
        $('connection-count').textContent = 'Carregando todas as conexões…';
        $('environment-filter').value = '';
        $('type-filter').value = '';
        $('connection-search').value = '';
        const environments = (
            await api('/clients/' + client.id + '/environments')
        ).items;
        if (generation !== state.clientLoad) return;
        state.environments = environments;
        const filter = $('environment-filter');
        filter.replaceChildren(
            new Option('Todos', ''),
            ...state.environments.map((e) => new Option(e.name, e.id))
        );
        await rows();
        $('connections-title').focus();
    }
    async function rows(append = false) {
        const generation = ++state.rowsLoad,
            client = state.client;
        if (!client) return;
        const params = new URLSearchParams({
            q: $('connection-search').value,
            offset: append ? state.next || 0 : 0
        });
        if ($('environment-filter').value)
            params.set('environment_id', $('environment-filter').value);
        if ($('type-filter').value) params.set('type', $('type-filter').value);
        status('Carregando conexões…');
        const result = await api(
            '/clients/' + client.id + '/connections?' + params
        );
        if (generation !== state.rowsLoad || client !== state.client) return;
        status('');
        const tbody = $('connection-rows');
        if (!append) tbody.replaceChildren();
        for (const c of result.items) {
            const tr = element('tr');
            for (const value of [
                c.name,
                types[c.type],
                c.host,
                c.port,
                c.environment.name
            ])
                tr.append(element('td', value));
            const actions = element('td');
            actions.append(
                button('Detalhes / editar', () => editConnection(c)),
                button('Credencial', () => reveal(c.credential_id)),
                button('Arquivar', () =>
                    archive('/connections', c, () => rows())
                )
            );
            tr.append(actions);
            tbody.append(tr);
        }
        state.next = result.next_offset;
        $('more-connections').hidden = state.next === null;
        $('connection-count').textContent =
            result.total +
            ' conexões encontradas · ' +
            tbody.children.length +
            ' carregadas';
        if (!result.total) {
            const tr = element('tr'),
                td = element('td', 'Nenhuma conexão encontrada.');
            td.colSpan = 6;
            tr.append(td);
            tbody.append(tr);
        }
        if (state.next !== null) await rows(true);
    }
    async function archive(path, row, refresh) {
        if (
            !confirm(
                'Arquivar ' +
                    row.name +
                    '? Dependências ativas impedem esta operação.'
            )
        )
            return;
        await api(path + '/' + row.id + '?version=' + row.version, 'DELETE');
        await refresh();
    }
    function editEnvironment(row = null) {
        editor(
            row ? 'Editar ambiente' : 'Novo ambiente',
            (form) => {
                field(
                    form,
                    'name',
                    'Nome livre do ambiente',
                    row?.name,
                    'text',
                    true
                );
                for (const [key, label] of [
                    ['system', 'Sistema'],
                    ['internal_address', 'DNS/IP interno'],
                    ['external_address', 'DNS/IP externo'],
                    ['contacts', 'Contatos']
                ])
                    field(form, key, label, row?.[key]);
            },
            async (data) => {
                const value = Object.fromEntries(
                    [
                        'name',
                        'system',
                        'internal_address',
                        'external_address',
                        'contacts'
                    ].map((k) => [k, text(data, k)])
                );
                await api(
                    row
                        ? '/environments/' + row.id
                        : '/clients/' + state.client.id + '/environments',
                    row ? 'PATCH' : 'POST',
                    { ...value, ...(row ? { version: row.version } : {}) }
                );
                await openClient(state.client);
            }
        );
    }
    function manageEnvironments() {
        editor(
            'Ambientes de ' + state.client.name,
            (form) => {
                for (const env of state.environments) {
                    const line = element('p', env.name + ' ');
                    line.append(
                        button('Editar', () => {
                            $('editor').close();
                            editEnvironment(env);
                        }),
                        button('Arquivar', async () => {
                            await archive('/environments', env, () =>
                                openClient(state.client)
                            );
                            $('editor').close();
                        })
                    );
                    form.append(line);
                }
                if (!state.environments.length)
                    form.append(element('p', 'Nenhum ambiente cadastrado.'));
            },
            async () => {}
        );
        $('save-catalog').hidden = true;
    }
    async function editConnection(row = null) {
        state.credentials = await all('/credentials');
        if (!state.environments.length)
            throw new Error('Cadastre um ambiente antes da conexão.');
        if (!state.credentials.length)
            throw new Error(
                'Cadastre uma credencial compartilhada antes da conexão.'
            );
        $('save-catalog').hidden = false;
        editor(
            row ? 'Conexão — detalhes e edição' : 'Nova conexão',
            (form) => {
                field(form, 'name', 'Identificação', row?.name, 'text', true);
                const env = select(
                    form,
                    'environment_id',
                    'Ambiente',
                    [
                        ['', 'Selecione um ambiente'],
                        ...state.environments.map((e) => [e.id, e.name])
                    ],
                    row?.environment_id || $('environment-filter').value || ''
                );
                env.disabled = !!row;
                const type = select(
                    form,
                    'type',
                    'Tipo',
                    Object.entries(types),
                    row?.type || 'oracle'
                );
                field(form, 'host', 'Host/IP', row?.host, 'text', true);
                const port = field(
                    form,
                    'port',
                    'Porta',
                    row?.port || 1521,
                    'number',
                    true
                );
                port.min = 1;
                port.max = 65535;
                select(
                    form,
                    'credential_id',
                    'Credencial compartilhada',
                    state.credentials.map((c) => [c.id, c.name]),
                    row?.credential_id || state.credentials[0].id
                );
                const parameters = element('div');
                form.append(parameters);
                function parametersForType() {
                    parameters.replaceChildren();
                    const fields = {
                        oracle: ['service_name', 'sid', 'tns_alias'],
                        sqlserver: [
                            'database',
                            'instance',
                            'encrypt',
                            'trust_server_certificate'
                        ],
                        postgresql: ['database', 'sslmode'],
                        ssh: ['host_key_fingerprint'],
                        rdp: ['domain'],
                        sftp: ['host_key_fingerprint', 'initial_directory'],
                        scp: ['host_key_fingerprint', 'initial_directory']
                    }[type.value];
                    parameters.append(
                        element(
                            'p',
                            'Parâmetros específicos — Oracle: preencha somente serviço, SID ou alias TNS.'
                        )
                    );
                    for (const key of fields) {
                        if (
                            ['encrypt', 'trust_server_certificate'].includes(
                                key
                            )
                        ) {
                            const i = field(
                                parameters,
                                'param_' + key,
                                key,
                                '',
                                'checkbox'
                            );
                            i.checked =
                                row?.type === type.value
                                    ? !!row.parameters[key]
                                    : false;
                        } else
                            field(
                                parameters,
                                'param_' + key,
                                key,
                                row?.type === type.value
                                    ? row.parameters[key]
                                    : ''
                            );
                    }
                }
                type.addEventListener('change', () => {
                    parametersForType();
                    port.value = {
                        oracle: 1521,
                        sqlserver: 1433,
                        postgresql: 5432,
                        ssh: 22,
                        rdp: 3389,
                        sftp: 22,
                        scp: 22
                    }[type.value];
                });
                parametersForType();
                field(
                    form,
                    'notes',
                    'Observações (não inclua senhas)',
                    row?.notes,
                    'textarea'
                );
            },
            async (data) => {
                const parameters = {};
                for (const [k, v] of data.entries()) {
                    if (k.startsWith('param_') && v)
                        parameters[k.slice(6)] = [
                            'param_encrypt',
                            'param_trust_server_certificate'
                        ].includes(k)
                            ? true
                            : String(v);
                }
                if (text(data, 'type') === 'sqlserver')
                    for (const key of ['encrypt', 'trust_server_certificate'])
                        parameters[key] = data.has('param_' + key);
                const payload = {
                    name: text(data, 'name'),
                    type: text(data, 'type'),
                    host: text(data, 'host'),
                    port: Number(data.get('port')),
                    credential_id: text(data, 'credential_id'),
                    parameters,
                    notes: text(data, 'notes'),
                    ...(row ? { version: row.version } : {})
                };
                await api(
                    row
                        ? '/connections/' + row.id
                        : '/environments/' +
                              text(data, 'environment_id') +
                              '/connections',
                    row ? 'PATCH' : 'POST',
                    payload
                );
                await rows();
            }
        );
    }
    async function credentials() {
        panel('credentials-panel');
        state.credentials = await all('/credentials');
        const list = $('credential-list');
        list.replaceChildren();
        for (const credential of state.credentials) {
            const line = element('div');
            line.className = 'credential-row';
            line.append(
                element('strong', credential.name),
                button('Editar', async () =>
                    editCredential(await api('/credentials/' + credential.id))
                ),
                button('Consultar segredo', () => reveal(credential.id)),
                button('Arquivar', () =>
                    archive('/credentials', credential, credentials)
                )
            );
            list.append(line);
        }
        if (!state.credentials.length)
            list.textContent = 'Nenhuma credencial cadastrada.';
    }
    function editCredential(row = null) {
        $('save-catalog').hidden = false;
        editor(
            row ? 'Editar credencial compartilhada' : 'Nova credencial',
            (form) => {
                field(form, 'name', 'Identificação', row?.name, 'text', true);
                field(
                    form,
                    'username',
                    row ? 'Novo usuário (vazio preserva o atual)' : 'Usuário',
                    '',
                    'text',
                    !row
                );
                field(
                    form,
                    'password',
                    row ? 'Nova senha (vazio preserva a atual)' : 'Senha',
                    '',
                    'password',
                    !row
                );
                if (row) {
                    form.append(
                        element(
                            'p',
                            'Conexões afetadas: ' +
                                (row.connections
                                    .map((c) => c.name)
                                    .join(', ') || 'nenhuma')
                        )
                    );
                    field(
                        form,
                        'confirm_shared',
                        'Confirmo a alteração nas conexões listadas',
                        '',
                        'checkbox'
                    );
                }
            },
            async (data) => {
                const payload = { name: text(data, 'name') };
                for (const key of ['username', 'password'])
                    if (text(data, key)) payload[key] = text(data, key);
                if (row)
                    Object.assign(payload, {
                        version: row.version,
                        confirm_shared: data.has('confirm_shared')
                    });
                await api(
                    '/credentials' + (row ? '/' + row.id : ''),
                    row ? 'PATCH' : 'POST',
                    payload
                );
                await credentials();
            }
        );
    }
    async function reveal(id) {
        const secret = await api('/credentials/' + id + '/reveal', 'POST');
        $('secret-user').value = secret.username;
        $('secret-password').value = secret.password;
        $('secret-password').type = 'password';
        $('toggle-secret').textContent = 'Mostrar senha';
        $('secret-dialog').showModal();
    }
    function clearSecret() {
        $('secret-user').value = '';
        $('secret-password').value = '';
        $('secret-password').type = 'password';
    }
    $('secret-dialog').addEventListener('close', clearSecret);
    $('secret-dialog').addEventListener('cancel', clearSecret);
    window.addEventListener('pagehide', clearSecret);
    $('close-secret').onclick = () => {
        $('secret-dialog').close();
        clearSecret();
    };
    $('toggle-secret').onclick = () => {
        const input = $('secret-password');
        input.type = input.type === 'password' ? 'text' : 'password';
        $('toggle-secret').textContent =
            input.type === 'password' ? 'Mostrar senha' : 'Ocultar senha';
    };
    $('editor').addEventListener('close', () => {
        if (!$('editor').open) {
            $('editor-fields').replaceChildren();
            $('save-catalog').hidden = false;
        }
    });
    $('cancel-editor').onclick = () => $('editor').close();
    $('type-filter').append(
        ...Object.entries(types).map(
            ([value, label]) => new Option(label, value)
        )
    );
    $('view-clients').onclick = () => safe(clients);
    $('view-credentials').onclick = () => safe(credentials);
    $('new-client').onclick = () => editClient();
    $('edit-client').onclick = () => editClient(state.client);
    $('archive-client').onclick = () =>
        safe(() => archive('/clients', state.client, clients));
    $('new-environment').onclick = () => editEnvironment();
    $('manage-environments').onclick = manageEnvironments;
    $('new-connection').onclick = () => safe(() => editConnection());
    $('new-credential').onclick = () => editCredential();
    $('more-connections').onclick = () => safe(() => rows(true));
    let timer;
    $('client-search').oninput = () => {
        clearTimeout(timer);
        timer = setTimeout(() => safe(clients), 200);
    };
    $('filters').onsubmit = (event) => {
        event.preventDefault();
        safe(() => rows());
    };
    for (const id of ['environment-filter', 'type-filter'])
        $(id).onchange = () => safe(() => rows());
    $('clear-filters').onclick = () => {
        $('environment-filter').value = '';
        $('type-filter').value = '';
        $('connection-search').value = '';
        safe(() => rows());
    };
    safe(clients);
})();
