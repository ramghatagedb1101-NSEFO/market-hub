/**
 * On-time starts for the GitHub jobs (14 Nov 2026).
 *
 * From Fri 6 Nov 2026 GitHub started this repo's scheduled runs 6-9 hours late (close-estimate's 09:20 run at 17:06
 * IST, the 08:45 market loop at 16:26, live quotes twice a day). A run started by hand (workflow_dispatch) starts within
 * seconds. The always-on trading machine keeps the clock (trader/kicker.py, once a minute) and calls ?mode=kick at each
 * job's time; this starts the job with the relay's GitHub key (GH_PAT, already used for daily.yml and algo-sync.yml).
 * A relay time trigger was the alternative, but it needs a Google permission only the owner can grant (27 Oct 2026).
 *
 * Each job's own GitHub schedule stays as the backup: a scheduled run first calls ?mode=kick_seen and stops when the
 * machine's clock is alive and started that job without error. If the machine stops, the schedules run as before.
 */

const KICK_WORKFLOWS_ = ['library.yml', 'expiry-history.yml', 'kite-reminder.yml', 'insights.yml', 'summaries.yml',
  'source-health.yml', 'live.yml', 'market-loop.yml', 'expiry-tape.yml', 'close-estimate.yml', 'expiry-theta.yml',
  'algo-sync.yml', 'breeze.yml', 'daily.yml'];
const KICK_ALIVE_MS_ = 30 * 60 * 1000;   // the machine calls at least every 10 minutes

function kickKeyOk_(p) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  return !!relayKey && p.key === relayKey;
}

function kick_(p) {
  if (!kickKeyOk_(p)) return { error: 'key does not match RELAY_KEY' };
  const props = PropertiesService.getScriptProperties();
  props.setProperty('KICK_SEEN', String(Date.now()));
  const wfs = String(p.wf || '').split(',').map(s => s.trim()).filter(Boolean);
  if (!wfs.length) return { ok: true, started: {} };
  const repo = props.getProperty('GH_REPO'), pat = props.getProperty('GH_PAT');
  if (!repo || !pat) return { error: 'GH_REPO or GH_PAT missing' };
  const cache = CacheService.getScriptCache();
  const minute = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'yyyyMMddHHmm');
  const started = {}, todo = [];
  wfs.forEach(wf => {
    if (KICK_WORKFLOWS_.indexOf(wf) < 0) started[wf] = 'not allowed';
    else if (cache.get('kick_' + wf + '_' + minute)) started[wf] = 'already';   // a repeated call in the same minute
    else todo.push(wf);
  });
  if (todo.length) {
    let res = [];
    try {
      res = UrlFetchApp.fetchAll(todo.map(wf => ({
        url: 'https://api.github.com/repos/' + repo + '/actions/workflows/' + wf + '/dispatches',
        method: 'post', muteHttpExceptions: true, contentType: 'application/json',
        headers: { Authorization: 'Bearer ' + pat, Accept: 'application/vnd.github+json' },
        payload: JSON.stringify({ ref: 'main' }) })));
    } catch (e) { res = []; }
    const lock = LockService.getScriptLock(); lock.waitLock(10000);
    try {
      const last = JSON.parse(props.getProperty('KICK_LAST') || '{}');
      todo.forEach((wf, i) => {
        const code = res[i] ? res[i].getResponseCode() : 'error';
        started[wf] = code;
        last[wf] = { code: code, at: Date.now() };
        if (code === 204) cache.put('kick_' + wf + '_' + minute, '1', 300);
      });
      props.setProperty('KICK_LAST', JSON.stringify(last));
    } finally { lock.releaseLock(); }
    const bad = todo.filter(wf => started[wf] !== 204);
    if (bad.length && !cache.get('kick_mail')) {
      cache.put('kick_mail', '1', 21600);   // at most one email every 6 hours
      MailApp.sendEmail(Session.getEffectiveUser().getEmail(), 'Market Hub: a job could not be started on time',
        'At ' + Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm') + ' IST GitHub refused to start: ' +
        bad.map(wf => wf + ' (' + started[wf] + ')').join(', ') + '. Its own late schedule will run it instead.');
    }
  }
  return { ok: true, started: started };
}

/** For a scheduled run: is the machine's clock alive, and did it start this job without error lately? */
function kickSeen_(p) {
  if (!kickKeyOk_(p)) return { error: 'key does not match RELAY_KEY' };
  const props = PropertiesService.getScriptProperties();
  const seen = Number(props.getProperty('KICK_SEEN') || 0);
  const alive = Date.now() - seen < KICK_ALIVE_MS_;
  const wf = String(p.wf || '');
  const rec = JSON.parse(props.getProperty('KICK_LAST') || '{}')[wf];
  const win = (wf === 'expiry-history.yml' ? 8 * 24 : 26) * 3600 * 1000;   // weekly job / daily jobs
  const lastOk = !!rec && rec.code === 204 && Date.now() - rec.at < win;
  return { alive: alive, last_ok: lastOk, seen_s: seen ? Math.round((Date.now() - seen) / 1000) : null,
           last_at: rec ? Utilities.formatDate(new Date(rec.at), 'Asia/Kolkata', 'yyyy-MM-dd HH:mm') : null };
}
