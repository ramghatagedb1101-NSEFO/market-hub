/**
 * Market Hub push notifications (14 Oct 2026): the Kite login reminder, direct to the owner's iPhone
 * (Market Hub added to the Home Screen; iOS 16.4+ only). Subscriptions (one PushSubscription per
 * device) live in the script property PUSH_SUBS, capped at PUSH_MAX_SUBS, de-duplicated by endpoint.
 *
 * VAPID keys (changed 14 Oct 2026 evening, owner's request to need no key-copying): by default the
 * relay holds the pair. kite-reminder.yml's first run generates it on GitHub's runner (hub/push.py) and
 * stores it here once (push_keys_init, never overwritten); every later run reads it back through the
 * key-protected push_state. Nobody types or sees the private key. It sits behind RELAY_KEY, the same
 * key that already guards the Kite access token (mode=token), so the added exposure is small: anyone
 * with RELAY_KEY could at worst send notifications to the owner's own devices.
 * If GitHub secrets VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY are ever added, they take precedence: the sender
 * posts that public key here (push_key); a different key drops the relay-held private key and the
 * stored subscriptions (pushKeyChanged_), and each device then turns notifications off and on once.
 * The phone only ever gets the PUBLIC key (app_push_key, session-gated like every other app_ call).
 */
const VAPID_PUB_RE = /^[A-Za-z0-9_-]{87}$/;    // 65-byte uncompressed P-256 point, base64url, no padding
const VAPID_PRIV_RE = /^[A-Za-z0-9_-]{43}$/;   // 32-byte P-256 scalar, base64url, no padding
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
  return { subscriptions: pushSubsLoad_(props), kite_state: st.state, login_link: st.login_link || kiteLoginLink_(),
           vapid_public_key: props.getProperty('VAPID_PUBLIC_KEY') || '',
           vapid_private_key: props.getProperty('VAPID_PRIVATE_KEY') || '' };
}

/** Key-protected: used only when GitHub secrets hold the keys -- the sender posts that public key here
 * so the phone can read it. A different public key invalidates any relay-held private key. */
function pushKey_(key, body) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let p;
  try { p = JSON.parse(body); } catch (e) { return { error: 'bad JSON body' }; }
  if (!p.public_key || !VAPID_PUB_RE.test(p.public_key)) return { error: 'missing or malformed public_key' };
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty('VAPID_PUBLIC_KEY') !== p.public_key) pushKeyChanged_(props);
  props.setProperty('VAPID_PUBLIC_KEY', p.public_key);
  return { ok: true };
}

/** A new public key: the relay-held private key and every stored subscription belong to the old one,
 * so both go -- the sender then reports "no subscribed devices" instead of failing every morning, and
 * each device needs "Turn off notifications" then "Turn on notifications" once. */
function pushKeyChanged_(props) {
  props.deleteProperty('VAPID_PRIVATE_KEY');
  props.setProperty('PUSH_SUBS', '[]');
}

/** Key-protected: the sender's first run stores the pair it generated. Never overwrites an existing
 * pair -- every subscribed device is bound to its public key, so replacing it would silently break them.
 * A public key with no private key beside it (left by the GitHub-secrets route) can never be used from
 * here, so it is replaced. */
function pushKeysInit_(key, body) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let p;
  try { p = JSON.parse(body); } catch (e) { return { error: 'bad JSON body' }; }
  if (!p.public_key || !VAPID_PUB_RE.test(p.public_key) || !p.private_key || !VAPID_PRIV_RE.test(p.private_key)) {
    return { error: 'missing or malformed key pair' };
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return { error: 'busy, try again' };
  try {
    if (props.getProperty('VAPID_PUBLIC_KEY') && props.getProperty('VAPID_PRIVATE_KEY')) return { ok: true, created: false };
    if (props.getProperty('VAPID_PUBLIC_KEY')) pushKeyChanged_(props);   // orphaned public-only key
    props.setProperties({ VAPID_PUBLIC_KEY: p.public_key, VAPID_PRIVATE_KEY: p.private_key });
    return { ok: true, created: true };
  } finally {
    lock.releaseLock();
  }
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
