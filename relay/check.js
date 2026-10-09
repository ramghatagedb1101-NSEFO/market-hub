// Pre-deploy check for the relay. Run before pasting into Apps Script:   node relay/check.js
//
// `node --check relay/Admin.gs` is not enough: the admin page's browser script lives inside the
// ADMIN_HTML template literal, so node only sees a string. A mistake in that string (on 9 Oct, a
// `screen\'s` that the template literal turned into a bare `'`) breaks the whole page script in the
// browser -- every button silently does nothing -- while the server file still parses fine.
// This builds ADMIN_HTML exactly as Apps Script would and parses each <script> block it contains.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failed = false;
for (const f of ['Code.gs', 'Admin.gs']) {
  const file = path.join(__dirname, f);
  try { new vm.Script(fs.readFileSync(file, 'utf8'), { filename: f }); console.log(`${f}: server code parses`); }
  catch (e) { failed = true; console.log(`${f}: SERVER SYNTAX ERROR\n${e.stack.split('\n').slice(0, 3).join('\n')}`); }
}

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, 'Admin.gs'), 'utf8') + '\n;this.__html = ADMIN_HTML;', ctx);
const blocks = [...ctx.__html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
blocks.forEach((src, i) => {
  try { new vm.Script(src, { filename: `admin-page-script-${i}.js` }); console.log(`Admin page script ${i}: parses`); }
  catch (e) {
    failed = true;
    const line = Number((e.stack.match(/admin-page-script-\d+\.js:(\d+)/) || [])[1]);
    console.log(`Admin page script ${i}: BROWSER SYNTAX ERROR: ${e.message}`);
    if (line) src.split('\n').slice(Math.max(0, line - 2), line + 1).forEach((l, k) => console.log(`  ${line - 1 + k}: ${l}`));
  }
});
if (!blocks.length) { failed = true; console.log('Admin page: no <script> block found in ADMIN_HTML'); }
process.exit(failed ? 1 : 0);
