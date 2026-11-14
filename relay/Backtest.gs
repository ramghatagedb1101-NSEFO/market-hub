/**
 * Back-tests page (14 Nov 2026; owner: "the backtest in a separate tab ... a query builder like tradl.ai").
 * The owner writes the back-test in plain English; Google's Gemini (free tier) turns it into the strategy builder's
 * own settings (trader/strategies/rules.py), shown as cards the owner can correct before running.
 *
 * GEMINI_API_KEY: the project's settings list is read-only above 50 properties, so the owner pastes the key into the
 * dashboard (Data and settings > Gemini key) and adminGeminiKeySave stores it. Never returned to any page.
 */

const BT_MODELS = ['gemini-3.8-flash', 'gemini-3.5-flash-lite'];   // the same free models as hub/summaries.py

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
  'Output: {"strategy": S, "period_months": N|null, "understood": {"instrument","entry","option","exit","period"},',
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
  ' {"type":"change","from":"prev_close"|"open","op":"above"|"below","pct":x}  (signed percent move of the index)',
  ' {"type":"dte","op":"<="|">=","days":n}   {"type":"weekday","days":[1..5]}  (1 = Monday)',
  ' {"type":"compare","left":OP,"op":">"|"<"|">="|"<="|"crosses_above"|"crosses_below","right":OP,"tf":5}',
  '  OP = {"src": price|open|high|low|close|day_open|day_high|day_low|prev_close|prev_high|prev_low|orb_high|orb_low|',
  '   ema|sma|rsi|atr|adx|chg_prev|chg_open|opt_price|dte|value, "n": period (ema/sma/rsi/atr/adx/orb), "value": x}',
  'Gap down 1% = {"type":"change","from":"prev_close","op":"below","pct":-1}. "price closes above the day open" =',
  ' compare close > day_open. "Last 6 months" = period_months 6; none given = null (all data).'
].join('\n');

/** Plain English -> strategy settings, through Gemini. */
function adminBtParse(token, text) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const q = String(text || '').trim().slice(0, 1500);
  if (q.length < 8) return { error: 'Describe the back-test in a sentence or two.' };
  const key = PropertiesService.getScriptProperties().getProperty('GEMINI_API_KEY');
  if (!key) return { error: 'no_key' };
  const body = { systemInstruction: { parts: [{ text: BT_GUIDE }] },
                 contents: [{ role: 'user', parts: [{ text: q }] }],
                 generationConfig: { responseMimeType: 'application/json', temperature: 0 } };
  let last = '';
  for (let i = 0; i < BT_MODELS.length; i++) {
    const r = UrlFetchApp.fetch('https://generativelanguage.googleapis.com/v1beta/models/' + BT_MODELS[i] + ':generateContent',
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
      } catch (e) { last = 'the AI answer could not be read'; continue; }
    }
    last = code === 400 || code === 403 ? 'Google refused the Gemini key; paste it again under Data and settings'
         : code === 429 ? 'the free Gemini allowance is busy; try again in a minute' : 'Gemini did not answer (' + code + ')';
    if (code === 400 || code === 403) break;
  }
  return { error: last };
}
