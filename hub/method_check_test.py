import sys, subprocess, tempfile, pathlib, io, contextlib
# Tests for hub/method_check.py (the METHOD.md guard). Run from the repo root: python -m hub.method_check_test
sys.path.insert(0, '.')
import hub.method_check as mc
R = []
def git(d, *a, msg=None):
    subprocess.run(['git', *a], cwd=d, check=True, capture_output=True)
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
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); mc.ROOT = d
    (d/'hub').mkdir(); (d/'relay').mkdir()
    (d/'hub/x.py').write_text('K = 0.88\n'); (d/'relay/y.gs').write_text('const S = [1, 2];\n'); (d/'METHOD.md').write_text(DOC)
    (d/'other.py').write_text('a=1\n')
    git(d,'init','-q','-b','main'); git(d,'-c','user.name=t','-c','user.email=t@t','commit','-qam','x') if False else None
    git(d,'add','.'); git(d,'-c','user.name=t','-c','user.email=t@t','commit','-qm','init')
    def commit(m): git(d,'add','.'); git(d,'-c','user.name=t','-c','user.email=t@t','commit','-qm',m)
    def run(*a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = mc.main(list(a))
        return rc, buf.getvalue()
    rc, out = run(); R.append(('clean doc passes', rc == 0))
    # non-engine change
    (d/'other.py').write_text('a=2\n'); commit('other'); rc,out = run(); R.append(('non-engine change passes', rc == 0 and 'no prediction-engine' in out))
    # engine change without doc
    (d/'relay/y.gs').write_text('const S = [1, 2];\nconst T = 1;\n'); commit('engine'); rc,out = run(); R.append(('engine change without doc fails', rc == 1 and 'relay/y.gs' in out))
    # same with escape
    (d/'relay/y.gs').write_text('const S = [1, 2];\nconst T = 2;\n'); commit('refactor [method: no change]'); rc,out = run(); R.append(('escape phrase passes', rc == 0))
    # engine + doc together, value changed and doc synced
    (d/'hub/x.py').write_text('K = 0.9\n'); commit('k'); rc,out = run('--settings-only'); R.append(('value drift fails', rc == 1 and "code says '0.9'" in out))
    rc,out = run('--write','--settings-only'); R.append(('--write syncs', rc == 0 and '`0.9`' in (d/'METHOD.md').read_text()))
    commit('doc'); rc,out = run('--base','HEAD~2'); R.append(('engine+doc in range passes', rc == 0 and 'updated with them' in out))
    # range: base older than several commits, doc changed in one of them
    rc,out = run('--base','0000000000000000000000000000000000000000'); R.append(('zero base -> HEAD~1', rc == 0))
    rc,out = run('--base','deadbeef'); R.append(('unknown base noted, not failed', rc == 0 and 'not in this clone' in out))
    # renamed constant
    (d/'relay/y.gs').write_text('const S2 = [1, 2];\n'); commit('rename'); rc,out = run('--settings-only'); R.append(('missing constant fails', rc == 1 and 'not found' in out))
    rc,out = run('--write','--settings-only'); R.append(('--write still fails on missing constant', rc == 1))
    # pipe in value round trip
    (d/'relay/y.gs').write_text("const S = 'a|b';\n"); rc,out = run('--write','--settings-only'); rc2,out2 = run('--settings-only')
    R.append(('pipe value round-trips', rc2 == 0 and r'`a\|b`' in (d/'METHOD.md').read_text().replace("'", "")))
# METHOD.md in the private repo, checked out INSIDE this repo as the GitHub job does (./market-hub-private)
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); mc.ROOT = d
    def commit(c, m, date):
        import os
        env = dict(os.environ, GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date)
        subprocess.run(['git', 'add', '.'], cwd=c, check=True, capture_output=True)
        subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', m], cwd=c, check=True, capture_output=True, env=env)
    def run(*a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf): rc = mc.main(list(a))
        return rc, buf.getvalue()
    (d/'relay').mkdir(); (d/'relay/y.gs').write_text('const S = [1, 2];\n'); (d/'.gitignore').write_text('market-hub-private/\n')
    git(d, 'init', '-q', '-b', 'main'); commit(d, 'init', '2026-10-15T10:00:00+05:30')
    pv = d/'market-hub-private'; pv.mkdir(); (pv/'METHOD.md').write_text(DOC.replace('- `hub/x.py`\n', '').replace('| `K` | `0.88` | `hub/x.py` | trial band |\n', ''))
    git(pv, 'init', '-q', '-b', 'main'); commit(pv, 'doc', '2026-10-15T10:30:00+05:30')
    (d/'relay/y.gs').write_text('const S = [1, 2];\nconst T = 1;\n'); commit(d, 'engine', '2026-10-15T10:40:00+05:30')
    rc, out = run('--doc', str(pv/'METHOD.md'), '--base', 'HEAD~1')
    R.append(('private copy inside the repo (GitHub layout), doc newer than base: passes', rc == 0 and 'private repo' in out))
    (d/'relay/y.gs').write_text('const S = [1, 2];\nconst T = 2;\n'); commit(d, 'base after doc', '2026-10-15T10:50:00+05:30')
    (d/'relay/y.gs').write_text('const S = [1, 2];\nconst T = 3;\n'); commit(d, 'engine again', '2026-10-15T10:55:00+05:30')
    rc, out = run('--doc', str(pv/'METHOD.md'), '--base', 'HEAD~1')
    R.append(('private copy inside the repo, doc older than base: fails', rc == 1))
for n, ok in R: print(('PASS' if ok else 'FAIL'), n)
print('ALL PASS' if all(ok for _, ok in R) else 'FAILURES')
