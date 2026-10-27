#!/usr/bin/env python3
"""Clause-to-test matrix for a feature contract.

A contract numbers its behaviour rules with ids like S5.3 (letter, slice
number, dot, clause number), written in bold: **S5.3**. A test proves a clause
by carrying the id in its name (test_s5_03_night_edge, test_s5_3_...) or as a
literal in a comment or string (S5.3). This prints one line per clause with
the files that mention it, or GAP.

usage: check_clauses.py CONTRACT.md [--tests DIR ...] [--strict]

--tests defaults to tests/unit and tests/hil under the contract's repo root
(the first parent directory that holds .git). --strict exits 1 on any GAP.
"""
import argparse
import os
import re
import sys

ID_RE = re.compile(r"\*\*([A-Z]\d+[a-z]?\.\d+)\*\*")
TEST_EXT = (".c", ".py")


def repo_root(path):
    d = os.path.dirname(os.path.abspath(path))
    while d and not os.path.exists(os.path.join(d, ".git")) and os.path.dirname(d) != d:
        d = os.path.dirname(d)
    return d


def rel(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:  # other drive on Windows
        return path


def clause_patterns(cid):
    """S5.3 -> literal 'S5.3' or snake 's5_3' / 's5_03' (case-insensitive)."""
    slice_, num = cid.split(".")
    snake = rf"{slice_.lower()}_0*{int(num)}(?!\d)"
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(cid)}(?!\d)|(?<![A-Za-z0-9]){snake}", re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("contract")
    ap.add_argument("--tests", nargs="*")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    try:
        with open(a.contract, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"cannot read {a.contract}: {e}")
    clauses = []
    for m in ID_RE.finditer(text):
        cid = m.group(1)
        if cid not in clauses:
            clauses.append(cid)
    if not clauses:
        print(f"no **S<n>.<m>** clause ids in {a.contract}")
        return 1 if a.strict else 0

    root = repo_root(a.contract)
    dirs = a.tests or [os.path.join(root, "tests", "unit"), os.path.join(root, "tests", "hil")]
    files = []
    for d in dirs:
        if not os.path.isdir(d):
            sys.exit(f"no such test dir: {d}")
        for dp, _, fns in os.walk(d):
            files += [os.path.join(dp, f) for f in fns if f.endswith(TEST_EXT)]
    bodies = {}
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                bodies[f] = fh.read()
        except OSError:
            pass

    gaps = 0
    for cid in clauses:
        pat = clause_patterns(cid)
        hits = sorted(rel(f, root) for f, b in bodies.items() if pat.search(b))
        if hits:
            print(f"{cid:8} {', '.join(hits)}")
        else:
            print(f"{cid:8} GAP")
            gaps += 1
    print(f"\n{len(clauses) - gaps}/{len(clauses)} clauses covered in {len(bodies)} test files")
    return 1 if (a.strict and gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
