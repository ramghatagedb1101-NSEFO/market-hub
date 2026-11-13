/**
 * ICICI Direct Breeze (13 Nov 2026): minute-by-minute futures and options history for back-tests, free with the
 * owner's ICICI account. Breeze needs one sign-in per day, like Kite. Its login sends the browser back to the phone
 * app (ICICI's form refused the relay's long address), which hands the day's session here (app_breeze_session, only
 * for a signed-in phone session). The download job (.github/workflows/breeze.yml) fetches it with RELAY_KEY
 * (?mode=breeze_session). The API key and secret stay in GitHub secrets; this stores only the day's session value.
 */

/** Saves the day's Breeze session from the phone app (owner signed in). */
function breezeSave_(token, apisession) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const s = String(apisession || '').trim();
  if (!/^[A-Za-z0-9]{4,64}$/.test(s)) return { error: 'not a Breeze session value' };
  const props = PropertiesService.getScriptProperties();
  props.setProperty('BREEZE_SESSION', s);
  props.setProperty('BREEZE_SESSION_DAY', todayIst_());
  return { ok: true, day: todayIst_() };
}

/** The download job reads today's session (RELAY_KEY, like ?mode=token for Kite). */
function breezeSessionForBatch_(p) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || p.key !== relayKey) return { error: 'key does not match RELAY_KEY' };
  const s = props.getProperty('BREEZE_SESSION'), day = props.getProperty('BREEZE_SESSION_DAY');
  if (!s || day !== todayIst_()) return { error: 'no ICICI sign-in today', day: day || null, today: todayIst_() };
  return { session: s, day: day };
}

/** Whether today's ICICI sign-in is done (phone app, signed in): no session value is returned. */
function breezeStatus_(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const props = PropertiesService.getScriptProperties();
  const day = props.getProperty('BREEZE_SESSION_DAY'), key = props.getProperty('BREEZE_API_KEY') || '';
  // The sign-in link carries the app's API key (ICICI's design); the owner adds BREEZE_API_KEY as a script property.
  return { today: day === todayIst_(), day: day || null,
           login: key ? 'https://api.icicidirect.com/apiuser/login?api_key=' + encodeURIComponent(key) : null };
}
