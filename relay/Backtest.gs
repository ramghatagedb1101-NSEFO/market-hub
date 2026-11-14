/**
 * Back-tests page (14 Nov 2026; owner: "the backtest in a separate tab ... a query builder like tradl.ai").
 * The owner writes the back-test in plain English; Google's Gemini (free tier) turns it into the strategy builder's
 * own settings (trader/strategies/rules.py), shown as cards the owner can correct before running.
 *
 * GEMINI_API_KEY: the project's settings list is read-only above 50 properties, so the owner pastes the key into the
 * dashboard (Data and settings > Gemini key) and adminGeminiKeySave stores it. Never returned to any page.
 */

// 14 Nov 2026 (hub/diag_gemini_speed.py, 12 timed calls with this page's prompt): gemini-3.5-flash-lite answered in
// 3.5-9 s and read both sides correctly; gemini-3.8-flash never answered (two waits past 100 s, ten "quota exceeded").
// Calls from Apps Script cannot be given a time limit, so the slow model is only tried last, and only early enough.
const BT_MODELS = ['gemini-3.5-flash-lite', 'gemini-3.8-flash'];

function adminGeminiKeySave(token, key) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  // 14 Nov 2026: a format check refused the owner's real key twice; Google itself now judges it (one free call to
  // list the models). Spaces, line breaks and quotes picked up by the copy are dropped first.
  const k = String(key || '').replace(/\s+/g, '').replace(/^["']+|["']+$/g, '');
  if (k.length < 20 || k.length > 400) return { error: 'Paste the whole key (it is a long line of letters and numbers).' };
  const r = UrlFetchApp.fetch('https://generativelanguage.googleapis.com/v1beta/models?pageSize=1',
    { headers: { 'x-goog-api-key': k }, muteHttpExceptions: true });
  const code = r.getResponseCode();
  if (code !== 200) return { error: 'Google did not accept this key (' + code + '). Copy it again from AI Studio.' };
  PropertiesService.getScriptProperties().setProperty('GEMINI_API_KEY', k);
  return { ok: true };
}

function adminGeminiKeyStatus(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return { set: !!PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY') };
}

const BT_GUIDE = [
  'You turn an Indian index-options back-test request into JSON settings. Answer with JSON only.',
  'Data available: NIFTY and BANKNIFTY index one-minute bars and their option prices (nearest expiry), Jan 2024 to now;',
  'NIFTY / BANKNIFTY Oct-Dec 2023 partly. NOT available: individual stocks, SENSEX trading, futures, VWAP, implied',
  'volatility / IV percentile, put-call ratio, open-interest signals, multi-leg trades (straddle, strangle, spread,',
  'iron condor), next-week or monthly expiry (nearest only). Anything not available goes in "unsupported" in plain',
  'words (e.g. "VWAP is not available yet"); never invent a substitute. If the request needs several legs, keep the',
  'first leg only and say so in "unsupported".',
  'Output: {"strategy": S, "period_months": N|null, "from": "YYYY-MM-DD"|null, "understood": {"instrument","entry","option","exit","period"},',
  ' "unsupported": [text]}. "understood" = one short plain-English line each, describing S exactly.',
  'S = {"name": short title, "index": "NIFTY"|"BANKNIFTY", "side": "BUY"|"SELL", "right": "C"|"P",',
  ' "strike": {"mode":"atm","steps":k} (k strikes out of the money, negative = in the money; "ATM+2 call" = steps 2,',
  '   "ATM-1 put" = steps -1 for puts means 1 in the money) or {"mode":"premium","near": rupees},',
  ' "expiry": "nearest", "lots": n,',
  ' "window": {"from":"HH:MM","until":"HH:MM"} (entry allowed only between; a fixed entry time T = from T until T+5min),',
  ' "groups": [{"match":"all"|"any","signals":[SIG...]}], "groups_match":"any"|"all",',
  ' "exits": {"sl_type":"pct"|"points","sl":x,"target_type":"pct"|"points","target":x (0 = none),',
  '   "trail_after_type":"pct","trail_after":x (0 = no trailing),"trail_type":"pct","trail":x,"exit_by":"HH:MM"},',
  ' "style": "intraday", "max_trades_day": n, "max_loss_day": rupees (0 = none), "reentry_gap": minutes}',
  'Percent stops/targets are on the option premium. Default exit_by 15:15, max_trades_day 1 when the request implies one',
  'trade a day, reentry_gap 15. No signal at all = enter at the window start: use signals [] is NOT allowed, so for a',
  'plain timed entry use {"type":"weekday","days":[1,2,3,4,5]}.',
  'SIG types (index-based, bars of tf = 1|3|5|15 minutes):',
  ' {"type":"price_ma","ma":"ema"|"sma","period":n,"tf":5,"op":"above"|"below"}',
  ' {"type":"ma_cross","ma":"ema"|"sma","fast":n,"slow":m,"tf":5,"dir":"up"|"down"}',
  ' {"type":"rsi","period":14,"tf":5,"op":"above"|"below"|"crosses_above"|"crosses_below","level":x}',
  ' {"type":"orb","minutes":15,"dir":"up"|"down"}  (index breaks the first N minutes high / low)',
  ' {"type":"supertrend","period":10,"mult":3,"tf":5,"dir":"buy"|"sell"|"up"|"down"}  (Supertrend: buy / sell =',
  '   it flips to Buy / Sell on that bar; up / down = in a Buy / Sell state; defaults 10 and 3)',
  ' BOTH DIRECTIONS: a request to buy the CALL on one signal and the PUT on another (e.g. call on Supertrend Buy, put on',
  '   Sell) is ONE strategy: side BUY, right C, "groups" = the call side signals, "put_groups" = the put side signals',
  '   (same format), "put_groups_match" any|all. The opposite signal closes the open option first. Set max_trades_day 10.',
  '   In "understood.entry" describe both sides.',
  ' {"type":"range_filter","per":100,"mult":3,"tf":5,"dir":"buy"|"sell"|"up"|"down"}  (Range Filter:',
  '   buy / sell = its Buy / Sell signal on that bar; up / down = it is in a Buy / Sell state; defaults 100 and 3)',
  ' {"type":"change","from":"prev_close"|"open","op":"above"|"below","pct":x}  (signed percent move of the index)',
  ' {"type":"dte","op":"<="|">=","days":n}   {"type":"weekday","days":[1..5]}  (1 = Monday)',
  ' {"type":"compare","left":OP,"op":">"|"<"|">="|"<="|"crosses_above"|"crosses_below","right":OP,"tf":5}',
  '  OP = {"src": price|open|high|low|close|day_open|day_high|day_low|prev_close|prev_high|prev_low|orb_high|orb_low|',
  '   ema|sma|rsi|atr|adx|chg_prev|chg_open|opt_price|dte|value, "n": period (ema/sma/rsi/atr/adx/orb), "value": x}',
  'Gap down 1% = {"type":"change","from":"prev_close","op":"below","pct":-1}. "price closes above the day open" =',
  ' compare close > day_open. "Last 6 months" = period_months 6, from null. "Since Aug 2026" / "from 1 Aug 2026" =',
  ' from "2026-08-01", period_months null. None given = both null (all data). A date before Jan 2024 or after today:',
  ' say so in unsupported.'
].join('\n');

/** Plain English -> strategy settings, through Gemini. */
function adminBtParse(token, text) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const q = String(text || '').trim().slice(0, 1500);
  if (q.length < 8) return { error: 'Describe the back-test in a sentence or two.' };
  const key = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  if (!key) return { error: 'no_key' };
  // 14 Nov 2026: Gemini did not know today's date and took "since Aug 2026" for the future (period dropped).
  const today = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'yyyy-MM-dd (EEEE)');
  const body = { systemInstruction: { parts: [{ text: 'Today is ' + today + ' (India). Data runs to yesterday.\n' + BT_GUIDE }] },
                 contents: [{ role: 'user', parts: [{ text: q }] }],
                 generationConfig: { responseMimeType: 'application/json', temperature: 0 } };
  let last = '';
  // 14 Nov 2026: the fast model three times (2 and 5 s apart, for "busy"), then the slow one once if time allows;
  // a model whose free allowance is used up (429) is not asked again.
  const tries = [[BT_MODELS[0], 0], [BT_MODELS[0], 2000], [BT_MODELS[0], 5000], [BT_MODELS[1], 0]];
  const t0 = Date.now(), spent = {};
  for (let i = 0; i < tries.length; i++) {
    if (spent[tries[i][0]]) continue;                   // that model's free allowance is used up for now
    // the slow model can take a minute or more: only start it while the page (90 s) can still wait for it
    if (Date.now() - t0 > (tries[i][0] === BT_MODELS[1] ? 20000 : 60000)) break;
    if (tries[i][1]) Utilities.sleep(tries[i][1]);
    const r = UrlFetchApp.fetch('https://generativelanguage.googleapis.com/v1beta/models/' + tries[i][0] + ':generateContent',
      { method: 'post', contentType: 'application/json', headers: { 'x-goog-api-key': key },
        payload: JSON.stringify(body), muteHttpExceptions: true });
    const code = r.getResponseCode();
    if (code === 200) {
      try {
        const j = JSON.parse(r.getContentText());
        const out = JSON.parse(j.candidates[0].content.parts[0].text);
        if (!out || !out.strategy) throw new Error('no strategy');
        out.query = q;
        return out;
      } catch (e) { last = "The AI's answer could not be read. Try again."; continue; }
    }
    last = code === 400 || code === 403 ? 'Google refused the Gemini key; paste it again under Data and settings'
         : code === 429 || code >= 500 ? "Google's free AI is busy right now. Try again in a minute." : "Google's AI did not answer (" + code + '). Try again in a minute.';
    if (code === 400 || code === 403) break;
    if (code === 429) spent[tries[i][0]] = true;
  }
  return { error: last || "Google's AI did not answer in time. Try again." };
}

/* ---- Back-tests on the trading machine (14 Nov 2026) ----------------------------------------------------------
 * adminBacktestStart queues a back-test here when the machine's worker (trader/bt_worker.py) has asked in the last
 * 90 s and it is outside market hours; otherwise it goes to GitHub as before. The worker asks with RELAY_KEY and
 * waits here up to 20 s for a job, so a queued back-test starts within a second without the worker calling often. */
function btMarketHours_() {
  const d = new Date(), wd = Number(Utilities.formatDate(d, 'Asia/Kolkata', 'u')), hm = Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm');
  return wd <= 5 && hm >= '09:10' && hm <= '15:35';
}
function btWorkerReady_() {
  const seen = Number(PropertiesService.getScriptProperties().getProperty('BT_WORKER_SEEN') || 0);
  return !btMarketHours_() && Date.now() - seen < 90000;
}
function btQueuePush_(id) {
  const lock = LockService.getScriptLock(); lock.waitLock(10000);
  try {
    const props = PropertiesService.getScriptProperties();
    const q = JSON.parse(props.getProperty('BT_QUEUE') || '[]').filter(x => x !== id);
    q.push(id); props.setProperty('BT_QUEUE', JSON.stringify(q.slice(-20)));
  } finally { lock.releaseLock(); }
}
function btNext_(p) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || p.key !== relayKey) return { error: 'key does not match RELAY_KEY' };
  for (let i = 0; i < 20; i++) {
    props.setProperty('BT_WORKER_SEEN', String(Date.now()));
    const lock = LockService.getScriptLock(); lock.waitLock(10000);
    let id = null;
    try {
      const q = JSON.parse(props.getProperty('BT_QUEUE') || '[]');
      if (q.length) { id = q.shift(); props.setProperty('BT_QUEUE', JSON.stringify(q)); }
    } finally { lock.releaseLock(); }
    if (id) return { id: id };
    Utilities.sleep(1000);
  }
  return {};
}
