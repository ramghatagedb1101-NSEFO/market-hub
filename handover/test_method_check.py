import sys, subprocess, tempfile, pathlib, io, contextlib
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
for n, ok in R: print(('PASS' if ok else 'FAIL'), n)
print('ALL PASS' if all(ok for _, ok in R) else 'FAILURES')
