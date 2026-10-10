/**
 * Kite login alarm (11 Oct 2026). A Kite developer app has one valid token at a time: any other login
 * with the same app cancels the relay's copy, which still looks valid (it is dated today) until Kite
 * refuses it. On 10 Oct that went unnoticed for hours and surfaced only as a broken chart.
 *
 * Every relay call to Kite reports a refusal here (kiteFailed_). The first refusal of a login is
 * recorded in the script property KITE_STATUS and emailed to the owner once, with the login link; the
 * phone's status bar and the dashboard show it until a fresh login through the relay clears it
 * (kiteLoginOk_, called from handleLogin_). The live-quotes job calls the relay every 5 minutes in
 * market hours, so a cancelled login is caught within minutes on a trading day.
 */
function kiteLoginLink_() {
  const apiKey = PropertiesService.getScriptProperties().getProperty('KITE_API_KEY') || '';
  return 'https://kite.zerodha.com/connect/login?v=3&api_key=' + encodeURIComponent(apiKey);
}

function kiteStatus_() {
  const props = PropertiesService.getScriptProperties();
  let st = {};
  try { st = JSON.parse(props.getProperty('KITE_STATUS') || '{}'); } catch (e) { st = {}; }
  const today = todayIst_();
  const loggedToday = props.getProperty('KITE_TOKEN_DATE') === today && !!props.getProperty('KITE_ACCESS_TOKEN');
  if (!loggedToday) return { state: 'no_login', login_link: kiteLoginLink_() };
  if (st.state === 'rejected' && st.token_date === today) return { state: 'rejected', at: st.at, login_link: kiteLoginLink_() };
  return { state: 'ok', login_at: st.login_at || null };
}

// Called with Kite's error message from any relay call; only a refused login counts.
function kiteFailed_(msg) {
  if (!/api_key|access_token|token/i.test(String(msg || ''))) return;
  const props = PropertiesService.getScriptProperties();
  let st = {};
  try { st = JSON.parse(props.getProperty('KITE_STATUS') || '{}'); } catch (e) { st = {}; }
  const today = todayIst_();
  if (st.state === 'rejected' && st.token_date === today) return;      // already recorded and emailed
  const at = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm');
  props.setProperty('KITE_STATUS', JSON.stringify({ state: 'rejected', at: at, token_date: today, login_at: st.login_at || null }));
  try {
    MailApp.sendEmail(Session.getEffectiveUser().getEmail(), 'Market Hub: Kite login was replaced - log in again',
      'At ' + at + ' IST Kite refused the login the relay saved' + (st.login_at ? ' at ' + st.login_at : '') + ' today ("' + msg + '").\n\n' +
      'This happens when another login is made with the same Kite developer app (another link, script or tool), ' +
      'or after a Kite logout or security reset. Until you log in again, live quotes, candle charts and the Kite ' +
      'parts of the daily job are unavailable (charts fall back to NSE daily closes).\n\n' +
      'Log in again (the usual route; it ends on the relay page):\n' + kiteLoginLink_());
  } catch (e) { /* the banners still show it */ }
}

function kiteLoginOk_() {
  PropertiesService.getScriptProperties().setProperty('KITE_STATUS', JSON.stringify({
    state: 'ok', token_date: todayIst_(), login_at: Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm') }));
}

/** Dashboard banner. */
function adminKiteStatus(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return kiteStatus_();
}
