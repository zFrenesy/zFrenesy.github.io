#!/usr/bin/env node
// Build-time TeX renderer: JSON lines in, JSON lines out.
//
//   input:  {"id": "...", "text": "...", "preserveCollection": false, "inferInlineMath": true, "economics": false}
//   output: {"id": "...", "html": "..."}  or  {"id": "...", "error": "..."}
//
// The extracted legacy formatter runs inside a vm context that has no require,
// process, filesystem or network access. Each document gets a time limit, so a
// pathological input cannot stall the build. Document text is data only.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const vm = require('node:vm');

const TIMEOUT_MS = Number(process.env.RP_RENDER_TIMEOUT_MS || 10000);
const sandbox = Object.create(null);
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
const context = vm.createContext(sandbox, { codeGeneration: { strings: false, wasm: false } });
for (const file of ['tex-bare-math.js', 'format-tex.js', 'economics-normalize.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), context, { filename: file });
}
const call = new vm.Script('formatTeX(__input.economics ? normalizedEconomicsStatement(__input.text) : __input.text, __input.preserveCollection, __input.inferInlineMath)');

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', line => {
    if (!line.trim()) return;
    const request = JSON.parse(line);
    let reply;
    try {
        sandbox.__input = {
            text: String(request.text),
            preserveCollection: Boolean(request.preserveCollection),
            inferInlineMath: request.inferInlineMath !== false,
            economics: Boolean(request.economics),
        };
        const html = call.runInContext(context, { timeout: TIMEOUT_MS });
        reply = { id: request.id, html: String(html) };
    } catch (err) {
        reply = { id: request.id, error: String(err && err.message || err).slice(0, 500) };
    } finally {
        delete sandbox.__input;
    }
    process.stdout.write(JSON.stringify(reply) + '\n');
});
