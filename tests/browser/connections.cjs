// Regressão visual/funcional contra servidor local e dados sintéticos.
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const assert = require('node:assert/strict');
(async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        const context = await browser.newContext({
            viewport: { width: 1440, height: 1000 }
        });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (error) => errors.push(error.message));
        const origin = 'http://127.0.0.1:18765';
        const name = 'Cliente sintético ' + Date.now();
        await page.goto(origin + '/login?next=/connections');
        await page.locator('#username').fill('reader');
        await page.locator('#password').fill('synthetic-password');
        await page.getByRole('button', { name: 'Entrar →' }).click();
        await page.waitForURL('**/connections');
        await page.locator('#new-connection-global').click();
        await page.locator('[name=client_name]').fill(name);
        await page.locator('[name=environment_name]').fill('PROD');
        await page.locator('[name=name]').fill('Servidor Linux');
        await page.locator('[name=type]').selectOption('ssh');
        await page.locator('[name=host]').fill('synthetic.internal');
        await page.locator('[name=username]').fill('synthetic-user');
        await page.locator('[name=password]').fill('synthetic-secret');
        for (const width of [1440, 768, 390]) {
            await page.setViewportSize({ width, height: 1000 });
            assert.equal(
                await page.evaluate(
                    () => document.documentElement.scrollWidth <= innerWidth
                ),
                true,
                'page overflow'
            );
            const a11y = await new AxeBuilder({ page }).analyze();
            assert.deepEqual(
                a11y.violations.map((v) => v.id),
                [],
                'accessibility dialog'
            );
        }
        await page.setViewportSize({ width: 1440, height: 1000 });
        await page.locator('#save-catalog').click();
        await page.locator('#editor').waitFor({ state: 'hidden' });
        await page
            .getByRole('cell', { name: 'Servidor Linux', exact: true })
            .waitFor();
        assert.equal(
            await page.locator('#environment-filter').inputValue(),
            ''
        );
        assert.equal(await page.locator('#type-filter').inputValue(), '');
        // Filtros anteriores não podem esconder a próxima conexão salva.
        await page.locator('#type-filter').selectOption('rdp');
        await page
            .getByRole('cell', { name: 'Nenhuma conexão encontrada.' })
            .waitFor();
        await page.locator('#new-connection-global').click();
        assert.equal(
            (await page.locator('[name=client_id]').inputValue()) !== '',
            true
        );
        await page.locator('[name=environment_name]').fill('prod');
        await page.locator('[name=name]').fill('Banco Oracle');
        await page.locator('[name=host]').fill('oracle.synthetic');
        await page.locator('[name=param_service_name]').fill('SYNTHETIC');
        const credential = await page
            .locator('[name=credential_id] option')
            .nth(1)
            .getAttribute('value');
        await page.locator('[name=credential_id]').selectOption(credential);
        await page.locator('#save-catalog').click();
        await page.locator('#editor').waitFor({ state: 'hidden' });
        await page
            .getByRole('cell', { name: 'Banco Oracle', exact: true })
            .waitFor();
        assert.equal(await page.locator('#connection-rows tr').count(), 2);
        assert.equal(
            await page.locator('#environment-filter option').count(),
            2,
            'environment reused'
        );
        // Falha 409 deve manter todos os dados e a senha somente no formulário aberto.
        await page.locator('#new-connection-global').click();
        await page.locator('[name=environment_name]').fill('PROD');
        await page.locator('[name=name]').fill('Servidor Linux');
        await page.locator('[name=type]').selectOption('ssh');
        await page.locator('[name=host]').fill('duplicate.synthetic');
        await page.locator('[name=username]').fill('retry-user');
        await page.locator('[name=password]').fill('retry-secret');
        await page.locator('#save-catalog').click();
        await page.locator('#editor-error').waitFor({ state: 'visible' });
        assert.match(
            await page.locator('#editor-error').innerText(),
            /Nome ou vínculo/
        );
        assert.equal(
            await page.locator('[name=password]').inputValue(),
            'retry-secret'
        );
        await page.locator('[name=name]').fill('Terceiro servidor');
        // Simula refresh indisponível após commit: não pode pedir novo POST.
        await page.route('**/api/clients/*/environments', (route) =>
            route.fulfill({
                status: 503,
                json: { erro: 'Falha sintética de atualização.' }
            })
        );
        await page.locator('#save-catalog').click();
        await page.locator('#editor').waitFor({ state: 'hidden' });
        assert.match(
            await page.locator('#catalog-status').innerText(),
            /Conexão salva.*atualizar/
        );
        await page.unroute('**/api/clients/*/environments');
        await page.reload();
        await page.getByRole('button', { name, exact: true }).click();
        await page
            .getByRole('cell', { name: 'Terceiro servidor', exact: true })
            .waitFor();
        const row = page.locator('tr').filter({
            has: page.getByRole('cell', {
                name: 'Servidor Linux',
                exact: true
            })
        });
        await row.getByRole('button', { name: 'Detalhes / editar' }).click();
        assert.equal(
            await page.locator('[name=environment_name]').inputValue(),
            'PROD'
        );
        await page.locator('[name=environment_name]').fill('TREINA');
        await page.locator('[name=host]').fill('edited.synthetic');
        await page.locator('#save-catalog').click();
        await page.locator('#editor').waitFor({ state: 'hidden' });
        await page
            .getByRole('cell', { name: 'edited.synthetic', exact: true })
            .waitFor();
        await row.getByRole('cell', { name: 'TREINA', exact: true }).waitFor();
        await page.reload();
        await page.getByRole('button', { name, exact: true }).click();
        await row.getByRole('cell', { name: 'TREINA', exact: true }).waitFor();
        await row.getByRole('button', { name: 'Detalhes / editar' }).click();
        await page.locator('[name=environment_name]').fill('PROD');
        await page.locator('#save-catalog').click();
        await page.locator('#editor').waitFor({ state: 'hidden' });
        await row.getByRole('cell', { name: 'PROD', exact: true }).waitFor();
        assert.equal(
            await page.locator('#environment-filter option').count(),
            3
        );
        page.once('dialog', (dialog) => dialog.accept());
        await row.getByRole('button', { name: 'Arquivar' }).click();
        await row.waitFor({ state: 'detached' });
        await page.reload();
        await page.getByRole('button', { name, exact: true }).click();
        await page
            .getByRole('cell', { name: 'Banco Oracle', exact: true })
            .waitFor();
        assert.equal(await page.locator('#connection-rows tr').count(), 2);
        for (const width of [1440, 768, 390]) {
            await page.setViewportSize({ width, height: 1000 });
            assert.equal(
                await page.evaluate(
                    () => document.documentElement.scrollWidth <= innerWidth
                ),
                true
            );
            const a11y = await new AxeBuilder({ page }).analyze();
            assert.deepEqual(
                a11y.violations.map((v) => v.id),
                [],
                'accessibility listing'
            );
        }
        // O foco de teclado alcança a ação principal e abre o formulário.
        await page.locator('#new-connection-global').focus();
        await page.keyboard.press('Enter');
        await page.locator('#editor').waitFor({ state: 'visible' });
        assert.equal(
            await page.evaluate(() =>
                document
                    .querySelector('#editor')
                    .contains(document.activeElement)
            ),
            true
        );
        await page.keyboard.press('Escape');
        await page.locator('[name=password]').waitFor({ state: 'detached' });
        assert.equal(
            await page.locator('[name=password]').count(),
            0,
            'secrets cleared on close'
        );
        assert.deepEqual(errors, []);
        console.log(
            'PASS: login, criação integral, reutilização, filtros, erros, refresh, edição, arquivamento, recarga, teclado e axe em 1440/768/390px'
        );
    } finally {
        await browser.close();
    }
})().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
