// Pre-deploy check for the relay. Run before pushing to Apps Script:   node relay/check.js
//
// Parses every server file (*.gs) and every inline <script> block in every page (*.html), so a syntax
// error in either is caught before it reaches the live relay. On 9 Oct a `\'` inside the old
// ADMIN_HTML template literal broke the whole admin page script in the browser while `node --check`
// on Admin.gs passed; the page now lives in AdminPage.html, and this checks it directly.
// Also checks that every server function the page calls with google.script.run actually exists.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failed = false;
const dir = __dirname;
const gs = fs.readdirSync(dir).filter(f => f.endsWith('.gs')).sort();
const html = fs.readdirSync(dir).filter(f => f.endsWith('.html')).sort();

let serverSrc = '';
for (const f of gs) {
  const src = fs.readFileSync(path.join(dir, f), 'utf8');
  serverSrc += '\n' + src;
  try { new vm.Script(src, { filename: f }); console.log(`${f}: server code parses`); }
  catch (e) { failed = true; console.log(`${f}: SERVER SYNTAX ERROR\n${e.stack.split('\n').slice(0, 3).join('\n')}`); }
}
// All .gs files share one global scope in Apps Script: a duplicate top-level name breaks the project.
try { new vm.Script(serverSrc, { filename: 'all-server-files' }); console.log('server files together: no clashing top-level names'); }
catch (e) { failed = true; console.log('SERVER FILES CLASH: ' + e.message); }

const serverFns = new Set([...serverSrc.matchAll(/^function\s+([A-Za-z0-9_]+)\s*\(/gm)].map(m => m[1]));
for (const f of html) {
  const page = fs.readFileSync(path.join(dir, f), 'utf8');
  const blocks = [...page.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  blocks.forEach((src, i) => {
    try { new vm.Script(src, { filename: `${f}#script${i}` }); console.log(`${f} script ${i}: parses`); }
    catch (e) {
      failed = true;
      const line = Number((e.stack.match(/#script\d+:(\d+)/) || [])[1]);
      console.log(`${f} script ${i}: BROWSER SYNTAX ERROR: ${e.message}`);
      if (line) src.split('\n').slice(Math.max(0, line - 2), line + 1).forEach((l, k) => console.log(`  ${line - 1 + k}: ${l}`));
    }
  });
  // google.script.run.<...>.fnName(  and  call('fnName', ...)
  const called = new Set([
    ...[...page.matchAll(/\.(admin[A-Za-z0-9_]*)\s*\(/g)].map(m => m[1]),
    ...[...page.matchAll(/call\(\s*'([A-Za-z0-9_]+)'/g)].map(m => m[1]),
  ]);
  for (const fn of called) {
    if (!serverFns.has(fn)) { failed = true; console.log(`${f}: calls ${fn}() but no server file defines it`); }
    else if (fn.endsWith('_')) { failed = true; console.log(`${f}: calls ${fn}() — names ending in _ are private and cannot be called from a page`); }
  }
  if (called.size) console.log(`${f}: ${called.size} server calls all defined (${[...called].sort().join(', ')})`);
}
process.exit(failed ? 1 : 0);
