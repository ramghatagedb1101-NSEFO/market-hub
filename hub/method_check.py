"""Keeps METHOD.md in step with the code (15 Oct 2026).

METHOD.md is the one document that explains how the platform forecasts, scores and screens. Two checks keep it true:

1. Settings: every row of its "Settings in force" table names a top-level constant in a file (Python `NAME = value`,
   JS `const NAME = value`); the value in the table must equal the code's. `--write` rewrites the value column from
   the code (prose that quotes the number still has to be edited by hand).
2. Coverage: if the commits being checked change a prediction-engine file (METHOD.md's "Source map" list) but not
   METHOD.md, the check fails, unless a commit message says "[method: no change]" (a refactor or fix that leaves the
   method as described).

Run by .github/workflows/method-doc.yml on every push to main (a failure emails the pusher), and locally before a push:
    python -m hub.method_check --base origin/main      # both checks against what is not pushed yet
    python -m hub.method_check --write                 # sync the settings table's values from the code
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = "METHOD.md"
ESCAPE = "[method: no change]"
SETTINGS = ("<!-- settings:start -->", "<!-- settings:end -->")
ENGINE = ("<!-- engine-files:start -->", "<!-- engine-files:end -->")
ROW = re.compile(r"^\|\s*`([A-Za-z_][A-Za-z0-9_]*)`\s*\|(.*)\|\s*`([^`]+)`\s*\|(.*)\|\s*$")


def _block(text: str, marks: tuple[str, str]) -> tuple[int, int]:
    a, b = text.find(marks[0]), text.find(marks[1])
    if a < 0 or b < a:
        raise SystemExit(f"{DOC}: markers {marks[0]} ... {marks[1]} missing")
    return a + len(marks[0]), b


def _cell(value: str) -> str:
    return "`" + value.replace("|", "\\|") + "`"


def _uncell(cell: str) -> str:
    c = cell.strip()
    if c.startswith("`") and c.endswith("`"):
        c = c[1:-1]
    return c.replace("\\|", "|")


# ---- reading a constant from code -------------------------------------------------------------------------------

def py_value(src: str, name: str) -> str | None:
    """Top-level `NAME = value` (or `NAME: T = value`), as ast.unparse writes it (no comments, one line)."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return ast.unparse(node.value)
                if isinstance(t, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    for el, val in zip(t.elts, node.value.elts):
                        if isinstance(el, ast.Name) and el.id == name:
                            return ast.unparse(val)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and node.value:
            return ast.unparse(node.value)
    return None


def _js_statement(src: str, start: int) -> list[str]:
    """Text of the statement from `start` to its `;` (or end of line at depth 0), comments dropped, split into
    declarators at depth-0 commas."""
    out, parts, depth, i, n, last = [], [], 0, start, len(src), ""
    while i < n:
        ch = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in "'\"`":
            j = i + 1
            while j < n and src[j] != ch:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i, last = j + 1, ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and ch == ";":
            break
        elif depth == 0 and ch == "\n":
            k = i + 1                              # a statement without `;` ends at a line that cannot continue it
            while k < n and src[k] in " \t":
                k += 1
            if last not in ",=+-*/(" and src[k:k + 1] not in ",.+-*/?:)]}":
                break
        elif depth == 0 and ch == ",":
            parts.append("".join(out))
            out, last = [], ch
            i += 1
            continue
        out.append(ch)
        if not ch.isspace():
            last = ch
        i += 1
    parts.append("".join(out))
    return [re.sub(r"\s+", " ", p).strip() for p in parts]


def js_value(src: str, name: str) -> str | None:
    """Top-level (column 0) `const|let|var ... NAME = value ...;`, comments dropped, whitespace collapsed."""
    for m in re.finditer(r"^(?:const|let|var)\s+", src, re.M):
        for decl in _js_statement(src, m.end()):
            k, eq, v = decl.partition("=")
            if eq and k.strip() == name:
                return v.strip()
    return None


def code_value(path: str, name: str) -> str | None:
    f = ROOT / path
    if not f.is_file():
        return None
    src = f.read_text(encoding="utf-8")
    return py_value(src, name) if f.suffix == ".py" else js_value(src, name)


# ---- check 1: settings table ------------------------------------------------------------------------------------

def check_settings(text: str, write: bool = False) -> tuple[list[str], str]:
    a, b = _block(text, SETTINGS)
    lines, problems, rows = text[a:b].split("\n"), [], 0
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if not m:
            continue
        rows += 1
        name, cell, path, meaning = m.group(1), m.group(2), m.group(3), m.group(4)
        val = code_value(path, name)
        if val is None:
            problems.append(f"setting {name}: not found as a top-level constant in {path}")
            continue
        if _uncell(cell) != val:
            problems.append(f"setting {name} ({path}): METHOD.md says {_uncell(cell)!r}, code says {val!r}")
            if write:
                lines[i] = f"| `{name}` | {_cell(val)} | `{path}` |{meaning}|"
    if not rows:
        problems.append("settings table has no rows")
    new = text[:a] + "\n".join(lines) + text[b:] if write else text
    return problems, new


# ---- check 2: coverage ------------------------------------------------------------------------------------------

def engine_patterns(text: str) -> list[str]:
    a, b = _block(text, ENGINE)
    return re.findall(r"`([^`]+)`", text[a:b])


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def check_coverage(text: str, base: str | None, head: str = "HEAD") -> tuple[list[str], list[str]]:
    """Returns (problems, notes)."""
    if not base or set(base) == {"0"}:
        base = f"{head}~1"
    try:
        _git("cat-file", "-e", f"{base}^{{commit}}")
    except subprocess.CalledProcessError:
        return [], [f"base {base} not in this clone: coverage not checked"]
    changed = [p for p in _git("diff", "--name-only", base, head).split("\n") if p]
    pats = engine_patterns(text)
    hit = sorted({p for p in changed if any(fnmatch.fnmatch(p, g) for g in pats)})
    if not hit:
        return [], [f"no prediction-engine file changed in {base[:12]}..{head}"]
    if DOC in changed:
        return [], [f"engine files changed and {DOC} updated with them: {', '.join(hit)}"]
    if ESCAPE in _git("log", "--format=%B", f"{base}..{head}"):
        return [], [f"engine files changed, marked {ESCAPE}: {', '.join(hit)}"]
    return [f"prediction-engine files changed but {DOC} did not: {', '.join(hit)}. Update the section(s) that "
            f"describe them and add a line to its change history, or, if the method is unchanged, put "
            f"\"{ESCAPE}\" in the commit message."], []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="commit to compare against (default HEAD~1); a push passes the commit before it")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--write", action="store_true", help="rewrite the settings table's values from the code")
    ap.add_argument("--settings-only", action="store_true")
    a = ap.parse_args(argv)
    doc = ROOT / DOC
    text = doc.read_text(encoding="utf-8")
    problems, new = check_settings(text, write=a.write)
    if a.write and new != text:
        doc.write_text(new, encoding="utf-8")
        print(f"{DOC}: settings table synced from the code ({len(problems)} value(s) changed or missing)")
        problems = [p for p in problems if "not found" in p or "no rows" in p]
    notes = []
    if not a.settings_only:
        p2, notes = check_coverage(text, a.base, a.head)
        problems += p2
    for n in notes:
        print(n)
    for p in problems:
        print(f"::error title=METHOD.md out of step::{p}")
    if not problems:
        print(f"{DOC}: in step with the code")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
