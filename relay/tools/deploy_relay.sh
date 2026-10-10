#!/usr/bin/env bash
# relay/tools/deploy_relay.sh <repo> <clasp-folder-parent> <last-deployed-commit> <version-label>
# <clasp-folder-parent>/relay-live is the clasp project folder (.clasp.json).
# Every step must succeed; no pipes that could hide a failure.
set -euo pipefail
REPO="$1"; SP="$2"; PREV="$3"; LABEL="$4"
cd "$REPO"; NEW=$(git log -1 --format=%h -- relay/)
cd "$SP/relay-live"; clasp deployments > /dev/null
cd "$REPO"
echo "1. project still matches the last deployed commit $PREV"; node "$REPO/relay/tools/verify_content.js" "$PREV"
echo "2. relay checks"; node relay/check.js
for g in relay/*.gs; do f=$(basename "$g" .gs); cp "$g" "$SP/relay-live/$f.js"; done; cp relay/AdminPage.html "$SP/relay-live/AdminPage.html"
echo "3. push"; cd "$SP/relay-live"; clasp push -f > "$SP/push.log" 2>&1 || { cat "$SP/push.log"; exit 1; }
cd "$REPO"; echo "4. project now matches $NEW"; node "$REPO/relay/tools/verify_content.js" "$NEW"
cd "$SP/relay-live"; VLINE=$(clasp version "$LABEL ($NEW)"); echo "$VLINE"; V=$(echo "$VLINE" | grep -o '[0-9]\+' | tail -1)
cd "$REPO"; echo "5. version $V matches $NEW"; node "$REPO/relay/tools/verify_content.js" "$NEW" "$V"
cd "$SP/relay-live"
clasp deploy -i AKfycbwQZxgg5yCekhRX7O88GyLCMt_MHRkTSLyjA1HF7Zk6nNL14wjoDydD73IabaTyOiFV -V "$V" -d "Research dashboard (v$V)" > /dev/null
clasp deploy -i AKfycbye12r6sWmdKQhSA6cpFnKnSUFjBhKDUm9BF5mGXsFmqeWer8-F0uVOoZ6NVPXF4SZ1ww -V "$V" -d "Live relay + research dashboard (v$V)" > /dev/null
echo "6. deployed version $V from $NEW"
