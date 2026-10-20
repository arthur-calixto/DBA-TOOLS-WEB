/* Executa os scripts reais dos templates em VM com DOM mínimo e sem rede. */
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map();
function element() {
    return {
        innerHTML: '', textContent: '', style: {}, dataset: {}, listeners: {},
        files: [{}], children: [], disabled: false,
        classList: {add() {}, remove() {}},
        addEventListener(event, handler) { this.listeners[event] = handler; },
        appendChild(child) { this.children.push(child); },
        contains() { return true; },
        querySelector() { return {remove() {}}; },
    };
}
const copyButton = element();
copyButton.dataset.idx = '0';
const captured = {clipboard: null, alerts: [], fetches: []};
const context = vm.createContext({
    document: {
        getElementById(id) {
            if (!nodes.has(id)) nodes.set(id, element());
            return nodes.get(id);
        },
        createElement: element,
        querySelectorAll() { return [copyButton]; },
    },
    navigator: {clipboard: {writeText: async text => { captured.clipboard = text; }}},
    window: {isSecureContext: true},
    alert: text => captured.alerts.push(text),
    setTimeout() {},
    FormData: class {append() {}},
    fetch: async (url, options) => {
        captured.fetches.push({url, options});
        if (input.networkFailure) throw new Error(input.networkFailure);
        return {ok: input.ok !== false, json: async () => input.response};
    },
    payload: input.payload,
    copyButton,
});
vm.runInContext(input.common, context);
vm.runInContext(input.script, context);
(async () => {
    const result = await vm.runInContext(input.action, context);
    process.stdout.write(JSON.stringify({result, captured,
        html: nodes.get('resultado')?.innerHTML,
        pdfVisible: nodes.get('btn-pdf')?.style.display,
        buttonDisabled: nodes.get(input.page === 'dashboard' ? 'btn-executar' : 'btn-analisar')?.disabled,
        expanded: nodes.get('pills-0')?.children.map(child => child.textContent),
    }));
})().catch(error => { console.error(error); process.exit(1); });
