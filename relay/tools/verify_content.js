// node verify_content.js <commit> [versionNumber] -- compares the Apps Script project (or a version) with relay/* at <commit>.
const fs=require('fs'),os=require('os'),p=require('path'),crypto=require('crypto'),cp=require('child_process');
const [commit, ver] = process.argv.slice(2);
const rc=JSON.parse(fs.readFileSync(p.join(os.homedir(),'.clasprc.json'),'utf8')); const t=(rc.tokens&&rc.tokens.default)||rc.token;
const h=s=>crypto.createHash('sha1').update(String(s).replace(/\r\n/g,'\n').replace(/\n+$/,'')).digest('hex').slice(0,12);
const repoFiles = cp.execSync('git ls-tree --name-only '+commit+' relay/').toString().split('\n').filter(f=>/\.(gs|html)$/.test(f));
fetch('https://script.googleapis.com/v1/projects/13rGqOxSSC3aQzZGYjpDWT4NnNXUO_kjCQKeA4oo2pZ8MD22KEilKWR7s/content'+(ver?'?versionNumber='+ver:''),{headers:{Authorization:'Bearer '+t.access_token}}).then(r=>r.json()).then(j=>{
  if (j.error) { console.log('API error:', j.error.message); process.exitCode=2; return; }
  const live=Object.fromEntries(j.files.filter(f=>f.type!=='JSON').map(f=>[f.name,f.source]));
  let ok=true;
  for (const f of repoFiles){ const name=p.basename(f).replace(/\.(gs|html)$/,''); const a=h(cp.execSync('git show '+commit+':'+f).toString()), b=live[name]==null?'(missing)':h(live[name]); const m=a===b; ok=ok&&m; console.log((m?'match   ':'DIFFERS ')+name.padEnd(10),'repo',a,'project',b); }
  for (const n of Object.keys(live)) if (!repoFiles.some(f=>p.basename(f).replace(/\.(gs|html)$/,'')===n)) { ok=false; console.log('EXTRA in project:', n); }
  console.log(ok?'=> project matches '+commit:'=> MISMATCH'); process.exitCode=ok?0:1;
});
