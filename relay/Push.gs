/**
 * Market Hub push notifications (14 Oct 2026): the Kite login reminder, direct to the owner's iPhone
 * (Market Hub added to the Home Screen; iOS 16.4+ only). Subscriptions (one PushSubscription per
 * device) live in the script property PUSH_SUBS, capped at PUSH_MAX_SUBS, de-duplicated by endpoint.
 *
 * The VAPID private key never touches the relay: hub/push.py signs every push itself (pywebpush) from
 * the GitHub secret VAPID_PRIVATE_KEY. The relay only hands the phone the PUBLIC key (app_push_key,
 * session-gated like every other app_ call) and stores it (push_key, called once by the sender
 * workflow from its own VAPID_PUBLIC_KEY secret) -- the owner never pastes a key into Apps Script.
 */
const PUSH_MAX_SUBS = 5;

function pushSubsLoad_(props) {
  try {
    const v = JSON.parse(props.getProperty('PUSH_SUBS') || '[]');
    return Array.isArray(v) ? v : [];
  } catch (e) { return []; }
}

/** The phone's Settings calls this (app_push_key) before subscribing, to pass to pushManager.subscribe. */
function appPushKey_(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const key = PropertiesService.getScriptProperties().getProperty('VAPID_PUBLIC_KEY') || '';
  if (!key) return { error: 'Push is not set up on the relay yet.' };
  return { key: key };
}

/** sub: the browser's PushSubscription.toJSON() -- {endpoint, keys:{p256dh, auth}}. */
function appPushSubscribe_(token, sub) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  if (!sub || !sub.endpoint || !sub.keys || !sub.keys.p256dh || !sub.keys.auth) return { error: 'Not a valid push subscription.' };
  const props = PropertiesService.getScriptProperties();
  let subs = pushSubsLoad_(props).filter(function (s) { return s.endpoint !== sub.endpoint; });
  subs.push({ endpoint: sub.endpoint, keys: { p256dh: sub.keys.p256dh, auth: sub.keys.auth } });
  if (subs.length > PUSH_MAX_SUBS) subs = subs.slice(subs.length - PUSH_MAX_SUBS);   // keep the newest
  props.setProperty('PUSH_SUBS', JSON.stringify(subs));
  return { ok: true };
}

function appPushUnsubscribe_(token, endpoint) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const props = PropertiesService.getScriptProperties();
  const subs = pushSubsLoad_(props).filter(function (s) { return s.endpoint !== endpoint; });
  props.setProperty('PUSH_SUBS', JSON.stringify(subs));
  return { ok: true };
}

/** Key-protected (RELAY_KEY): hub/push.py's one call to decide who to send to and whether Kite is
 * already logged in today, so a reminder never fires after the owner has already logged in. */
function pushState_(p) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || !p.key || p.key !== relayKey) return { error: 'forbidden' };
  const props = PropertiesService.getScriptProperties();
  const st = kiteStatus_();
  return { subscriptions: pushSubsLoad_(props), kite_state: st.state, login_link: st.login_link || kiteLoginLink_() };
}

/** Key-protected: the kite-reminder.yml workflow posts VAPID_PUBLIC_KEY here once (from its own GitHub
 * secret), so the owner never has to open Apps Script's script-properties UI to paste it in. */
function pushKey_(key, body) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let p;
  try { p = JSON.parse(body); } catch (e) { return { error: 'bad JSON body' }; }
  if (!p.public_key) return { error: 'missing public_key' };
  PropertiesService.getScriptProperties().setProperty('VAPID_PUBLIC_KEY', p.public_key);
  return { ok: true };
}

/** Key-protected: hub/push.py calls this after Web Push reports an endpoint gone (404/410), so a
 * uninstalled/expired subscription does not keep being tried (and does not count against PUSH_MAX_SUBS). */
function pushDrop_(key, body) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let p;
  try { p = JSON.parse(body); } catch (e) { return { error: 'bad JSON body' }; }
  const drop = Array.isArray(p.endpoints) ? p.endpoints : [];
  if (!drop.length) return { ok: true, dropped: 0 };
  const props = PropertiesService.getScriptProperties();
  const before = pushSubsLoad_(props);
  const after = before.filter(function (s) { return drop.indexOf(s.endpoint) < 0; });
  props.setProperty('PUSH_SUBS', JSON.stringify(after));
  return { ok: true, dropped: before.length - after.length };
}
