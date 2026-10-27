import sys, subprocess, tempfile, pathlib, io, contextlib
# Tests for hub/method_check.py (the METHOD.md guard). Run from the repo root: python -m hub.method_check_test
# No network calls anywhere here: fetch_doc/doc_last_commit_ts/pull_doc/push_doc are monkeypatched, since the real
# ones talk to the private repo over the GitHub API (needs PRIVATE_REPO_TOKEN, which a test must never depend on).
sys.path.insert(0, '.')
import hub.method_check as mc
_real_doc_last_commit_ts = mc.doc_last_commit_ts
R = []
DOC = """# Method
<!-- settings:start -->
| Setting | Value | File | What it means |
|---|---|---|---|
| `K` | `0.88` | `hub/x.py` | trial band |
| `S` | `[1, 2]` | `relay/y.gs` | spreads |
<!-- settings:end -->
Source map
<!-- engine-files:start -->
- `hub/x.py`
- `relay/*.gs`
<!-- engine-files:end -->
"""


def run(**kw):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = mc.main(list(kw.pop("argv", [])))
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else 1
    return rc, buf.getvalue()


# ---- check_settings: a pure function, no repo/network needed at all ---------------------------------------------
mc.ROOT = pathlib.Path(tempfile.mkdtemp())
(mc.ROOT / 'hub').mkdir(); (mc.ROOT / 'relay').mkdir()
(mc.ROOT / 'hub/x.py').write_text('K = 0.88\n')
(mc.ROOT / 'relay/y.gs').write_text('const S = [1, 2];\n')

problems, new = mc.check_settings(DOC)
R.append(('clean settings table passes', problems == [] and new == DOC))

(mc.ROOT / 'hub/x.py').write_text('K = 0.9\n')
problems, new = mc.check_settings(DOC)
R.append(('value drift detected', len(problems) == 1 and "code says '0.9'" in problems[0] and new == DOC))

problems, new = mc.check_settings(DOC, write=True)
R.append(('--write syncs the value', '`0.9`' in new and '`0.88`' not in new))

(mc.ROOT / 'relay/y.gs').write_text('const S2 = [1, 2];\n')
problems, _ = mc.check_settings(DOC)
R.append(('renamed constant: missing, flagged', any('not found' in p for p in problems)))

(mc.ROOT / 'relay/y.gs').write_text("const S = 'a|b';\n")
_, new = mc.check_settings(DOC, write=True)
R.append(('pipe value escaped on write', r'a\|b' in new))
problems, _ = mc.check_settings(new)
R.append(('...and reads back clean', problems == []))

# ---- check_coverage: real git history for the PUBLIC repo side; the private-repo side is monkeypatched -----------
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); mc.ROOT = d

    def git(*a):
        subprocess.run(['git', *a], cwd=d, check=True, capture_output=True)

    def commit(m):
        git('add', '.'); git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', m)

    (d / 'relay').mkdir(); (d / 'other.py').write_text('a=1\n'); (d / 'relay/y.gs').write_text('const S = [1, 2];\n')
    git('init', '-q', '-b', 'main'); commit('init')

    base_t = int(subprocess.run(['git', 'show', '-s', '--format=%ct', 'HEAD'], cwd=d, check=True,
                                 capture_output=True, text=True).stdout.strip())

    (d / 'other.py').write_text('a=2\n'); commit('other')
    problems, notes = mc.check_coverage(DOC, 'HEAD~1')
    R.append(('non-engine change: no coverage problem', problems == [] and 'no prediction-engine' in notes[0]))

    (d / 'relay/y.gs').write_text('const S = [1, 2];\nconst T = 1;\n'); commit('engine, no doc')
    mc.doc_last_commit_ts = lambda: None
    problems, notes = mc.check_coverage(DOC, 'HEAD~1')
    R.append(('engine change, private repo unreadable: soft-pass, not a failure',
               problems == [] and 'not readable' in notes[0]))

    mc.doc_last_commit_ts = lambda: base_t - 100          # doc last touched BEFORE this code's base commit
    problems, notes = mc.check_coverage(DOC, 'HEAD~1')
    R.append(('engine change, doc older than base: fails', len(problems) == 1 and 'relay/y.gs' in problems[0]))

    mc.doc_last_commit_ts = lambda: base_t + 100          # doc touched AFTER base: counts as updated with the push
    problems, notes = mc.check_coverage(DOC, 'HEAD~1')
    R.append(('engine change, doc newer than base: passes', problems == [] and 'updated in the private repo' in notes[0]))

    mc.doc_last_commit_ts = lambda: base_t - 100
    (d / 'relay/y.gs').write_text('const S = [1, 2];\nconst T = 2;\n'); commit('refactor [method: no change]')
    problems, notes = mc.check_coverage(DOC, 'HEAD~1')
    R.append(('escape phrase passes even if the doc is stale', problems == [] and 'marked' in notes[0]))

    (d / 'other.py').write_text('a=3\n'); (d / 'METHOD.md').write_text(DOC); commit('doc landed in the public repo too')
    mc.doc_last_commit_ts = lambda: (_ for _ in ()).throw(AssertionError('should not be called'))
    problems, notes = mc.check_coverage(DOC, 'HEAD~2')
    R.append(('METHOD.md itself in the diff: passes without even checking the private repo',
               problems == [] and 'updated with them' in notes[0]))

    problems, notes = mc.check_coverage(DOC, '0000000000000000000000000000000000000000')
    R.append(('zero base -> HEAD~1', True))
    problems, notes = mc.check_coverage(DOC, 'deadbeef')
    R.append(('unknown base noted, not failed', problems == [] and 'not in this clone' in notes[0]))

# ---- doc_last_commit_ts: date parsing, and the "cannot tell" path -------------------------------------------------
mc.doc_last_commit_ts = _real_doc_last_commit_ts          # undo the earlier coverage test's trap lambda
mc._api_get = lambda url: [{"commit": {"committer": {"date": "2026-10-15T10:30:00Z"}}}]
import datetime as _dt
expected = int(_dt.datetime.fromisoformat('2026-10-15T10:30:00+00:00').timestamp())
R.append(('commit date parsed to the right epoch second', mc.doc_last_commit_ts() == expected))
mc._api_get = lambda url: []
R.append(('no commits at all: None, not a crash', mc.doc_last_commit_ts() is None))


def _boom(url):
    raise RuntimeError('network down')


mc._api_get = _boom
R.append(('network error: None, not a crash', mc.doc_last_commit_ts() is None))

# ---- main(): --pull / --push / --write plumbing, fetch_doc/pull_doc/push_doc all monkeypatched -------------------
calls = []
mc.pull_doc = lambda path: calls.append(('pull', path))
rc, out = run(argv=['--pull', '/tmp/x.md'])
R.append(('--pull calls pull_doc with the given path', rc == 0 and calls == [('pull', pathlib.Path('/tmp/x.md'))]))

calls.clear()
mc.push_doc = lambda path, message: (calls.append(('push', path, message)), 'abc1234')[1]
rc, out = run(argv=['--push', '/tmp/x.md', 'a message'])
R.append(('--push calls push_doc with path and message', rc == 0 and calls == [('push', pathlib.Path('/tmp/x.md'), 'a message')]
          and 'abc1234' in out))

with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); mc.ROOT = d
    (d / 'hub').mkdir(); (d / 'hub/x.py').write_text('K = 0.9\n')
    (d / 'relay').mkdir(); (d / 'relay/y.gs').write_text('const S = [1, 2];\n')

    target = d / 'edited.md'
    mc.DEFAULT_LOCAL = target                            # --write with no --doc defaults here; sandbox it
    mc.pull_doc = lambda path: path.write_text(DOC, encoding='utf-8')
    rc, out = run(argv=['--write', '--settings-only'])
    R.append(('--write with no --doc pulls a fresh copy, then syncs it',
              rc == 0 and '`0.9`' in target.read_text(encoding='utf-8') and 'review' in out))

    given = d / 'given.md'
    given.write_text(DOC)                                # an existing file named with --doc: used as-is, no pull
    rc, out = run(argv=['--doc', str(given), '--settings-only'])
    R.append(('--doc on an existing file: checked as-is', rc == 1 and "code says '0.9'" in out))

    missing = d / 'missing.md'
    rc, out = run(argv=['--doc', str(missing), '--settings-only'])
    R.append(('--doc on a missing file: clear error, not a crash', rc != 0))

    mc.fetch_doc = lambda: (DOC.replace('0.88', '0.9'), 'sha123')     # matches code's K = 0.9: no drift
    rc, out = run(argv=['--settings-only'])
    R.append(('no --doc at all: reads METHOD.md live via fetch_doc', rc == 0 and 'in step' in out))

for n, ok in R:
    print(('PASS' if ok else 'FAIL'), n)
print('ALL PASS' if all(ok for _, ok in R) else 'FAILURES')
sys.exit(0 if all(ok for _, ok in R) else 1)
