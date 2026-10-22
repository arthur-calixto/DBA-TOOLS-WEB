// TER-11: páginas reais, ZIP sintético e resultados de diagnóstico simulados.
const { chromium } = require('playwright');
const { default: AxeBuilder } = require('@axe-core/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
    const browser = await chromium.launch();
    const output = process.env.TER11_SCREENSHOTS || '/tmp/ter11-final-visual';
    fs.mkdirSync(output, { recursive: true });
    try {
        const context = await browser.newContext();
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (e) => errors.push(e.message));
        const origin = 'http://127.0.0.1:18765';
        async function verify(name, width, height) {
            await page.setViewportSize({ width, height });
            await page.evaluate(() => document.fonts.ready);
            assert.equal(
                await page.evaluate(
                    () => document.documentElement.scrollWidth <= innerWidth
                ),
                true,
                name + ' global overflow'
            );
            const small = await page.evaluate(() =>
                [...document.querySelectorAll('main *, .topbar *')]
                    .filter(
                        (e) =>
                            e.getClientRects().length &&
                            [...e.childNodes].some(
                                (n) => n.nodeType === 3 && n.textContent.trim()
                            ) &&
                            parseFloat(getComputedStyle(e).fontSize) < 14
                    )
                    .map((e) => e.tagName + '.' + e.className)
            );
            assert.deepEqual(small, [], name + ' font below 14px');
            assert.deepEqual(
                (await new AxeBuilder({ page }).analyze()).violations.map(
                    (v) => v.id
                ),
                [],
                name + ' axe'
            );
            const clipping = await page.evaluate(() =>
                [
                    ...document.querySelectorAll(
                        'button, label, input, select, textarea'
                    )
                ]
                    .filter(
                        (e) =>
                            !e.matches('.sr-only, .skip-link') &&
                            e.getClientRects().length &&
                            e.scrollWidth > e.clientWidth + 2 &&
                            !['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName)
                    )
                    .map((e) => e.tagName + ':' + e.textContent.slice(0, 50))
            );
            assert.deepEqual(clipping, [], name + ' clipped controls');
            await page.locator('#editor-fields').evaluateAll((nodes) =>
                nodes.forEach((e) => {
                    e.scrollTop = 0;
                })
            );
            await page.screenshot({
                path: path.join(output, `${name}-${width}.png`)
            });
        }
        await page.goto(origin + '/login');
        await verify('login', 1366, 768);
        await page.locator('#username').fill('admin');
        await page.locator('#password').fill('synthetic-password');
        await page.getByRole('button', { name: 'Entrar →' }).click();
        await page.waitForURL(origin + '/');
        for (const [w, h] of [
            [1920, 1080],
            [1366, 768],
            [390, 844]
        ])
            await verify('home', w, h);
        await page.goto(origin + '/monitor');
        await page
            .locator('#arquivo')
            .setInputFiles(process.env.TER11_MONITOR_ZIP);
        await page.locator('#btn-analisar').click();
        await page.locator('.monitor-table').waitFor();
        for (const [w, h] of [
            [1920, 1080],
            [1366, 768],
            [390, 844]
        ])
            await verify('monitor', w, h);
        await page.goto(origin + '/analise/allowed');
        await page.route('**/analise/allowed/executar', async (route) => {
            const checks = await page.evaluate(() => window.eval('checks'));
            const data = {};
            for (const check of checks)
                data[check.id] =
                    check.exibicao === 'cards'
                        ? [
                              {
                                  PARAMETRO: 'Parâmetro sintético',
                                  ATUAL: '100',
                                  ESPERADO: '200',
                                  STATUS: 'alerta'
                              }
                          ]
                        : check.exibicao === 'contagem'
                          ? [
                                {
                                    TITULO: 'Indicador sintético',
                                    CONTAGEM: 12,
                                    DETALHE: 'Exemplo técnico',
                                    STATUS: 'ok'
                                }
                            ]
                          : [
                                {
                                    IDENTIFICACAO: 'Registro sintético',
                                    TEMPO_MS: 150,
                                    STATUS: 'alerta'
                                }
                            ];
            await route.fulfill({ status: 200, json: data });
        });
        await page.locator('#btn-executar').click();
        await page.locator('#resultado section').first().waitFor();
        for (const [w, h] of [
            [1920, 1080],
            [1366, 768],
            [390, 844]
        ])
            await verify('analysis', w, h);
        await page.goto(origin + '/connections');
        await page.locator('#new-connection-global').click();
        await page.locator('[name=client_name]').fill('Cliente sintético');
        await page.locator('[name=environment_name]').fill('PROD');
        await page.locator('[name=name]').fill('Banco de homologação');
        await page.locator('[name=host]').fill('synthetic.internal');
        await page.locator('[name=param_service_name]').fill('SYNTHETIC');
        await page.locator('[name=username]').fill('synthetic');
        await page.locator('[name=password]').fill('synthetic-secret');
        for (const [w, h] of [
            [1920, 1080],
            [1366, 768],
            [390, 844]
        ]) {
            await verify('new-connection', w, h);
            const save = await page.locator('#save-catalog').boundingBox();
            assert.ok(
                save.y >= 0 && save.y + save.height <= h,
                'save button outside viewport'
            );
            assert.equal(
                await page
                    .locator('#editor')
                    .evaluate((e) => e.scrollWidth <= e.clientWidth + 1),
                true,
                'modal overflow'
            );
        }
        await page.locator('#save-catalog').click();
        await page.locator('#editor').waitFor({ state: 'hidden' });
        await page
            .getByRole('cell', { name: 'Banco de homologação', exact: true })
            .waitFor();
        for (const [w, h] of [
            [1920, 1080],
            [1366, 768],
            [390, 844]
        ])
            await verify('connections', w, h);
        await page.getByRole('button', { name: 'Detalhes / editar' }).click();
        for (const [w, h] of [
            [1920, 1080],
            [1366, 768],
            [390, 844]
        ])
            await verify('edit-connection', w, h);
        assert.deepEqual(errors, []);
        console.log(
            'PASS TER-11: login, home, monitor com ZIP, análise com resultados sintéticos, conexões e modais; fontes >=14px, axe, overflow e botões em 1920/1366/390. Capturas: ' +
                output
        );
    } finally {
        await browser.close();
    }
})().catch((e) => {
    console.error(e);
    process.exitCode = 1;
});
