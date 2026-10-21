const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const button = {disabled:false, textContent:'Sair', addEventListener:(_, handler) => button.click = handler};
const status = {textContent:''};
const captured = {};
const context = vm.createContext({
    document: {cookie:'dba_tools_csrf=synthetic-csrf', getElementById: id => id === 'logout' ? button : status},
    window: {location: {assign: value => captured.location = value}},
    fetch: async (url, options) => {
        captured.url = url; captured.options = options;
        if (input.networkFailure) throw Error('synthetic');
        return {ok: input.ok};
    },
});
vm.runInContext(fs.readFileSync('app/static/navigation.js', 'utf8'), context);
(async () => {
    await button.click();
    process.stdout.write(JSON.stringify({captured, disabled:button.disabled, text:status.textContent}));
})().catch(error => { console.error(error); process.exit(1); });
