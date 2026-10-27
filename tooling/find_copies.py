#!/usr/bin/env python3
"""Near-identical source files across repos: the second copy that should be
one SDK module.

Pairs files with the same basename across different roots and reports pairs
whose line similarity is at or above the threshold (difflib ratio on line
lists, comments and blank lines kept: a copy with edited comments is still a
copy).

usage: find_copies.py ROOT [ROOT ...] [--min 0.90] [--strict]

Each ROOT is a repo; its src/ (or lib/ for the SDK) is scanned. --strict
exits 1 when any pair is at or above --min.
"""
import argparse
import difflib
import os
import sys

SRC_EXT = (".c", ".h", ".py")
SKIP = {"main.c", "CMakeLists.txt", "__init__.py", "conftest.py", "Kconfig"}


def scan(root):
    out = {}
    for d in ("src", "lib"):
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = [x for x in dns if x not in ("build", "__pycache__")]
            for f in fns:
                if f.endswith(SRC_EXT) and f not in SKIP:
                    out.setdefault(f, []).append(os.path.join(dp, f))
    return out


def lines(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read().splitlines()
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="+")
    ap.add_argument("--min", type=float, default=0.90)
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    per_root = []
    for r in a.roots:
        r = os.path.abspath(r)
        if not os.path.isdir(r):
            sys.exit(f"no such dir: {r}")
        per_root.append((r, scan(r)))

    pairs = []
    for i in range(len(per_root)):
        for j in range(i + 1, len(per_root)):
            ra, fa = per_root[i]
            rb, fb = per_root[j]
            for name in sorted(set(fa) & set(fb)):
                for pa in fa[name]:
                    la = lines(pa)
                    if not la:
                        continue
                    for pb in fb[name]:
                        lb = lines(pb)
                        if not lb:
                            continue
                        sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
                        if sm.real_quick_ratio() < a.min or sm.quick_ratio() < a.min:
                            continue
                        ratio = sm.ratio()
                        if ratio >= a.min:
                            pairs.append((ratio, max(len(la), len(lb)), os.path.relpath(pa, ra), os.path.basename(ra),
                                          os.path.relpath(pb, rb), os.path.basename(rb)))
    pairs.sort(key=lambda p: (-p[1] * p[0], p[2]))
    total = 0
    for ratio, n, pa, ra, pb, rb in pairs:
        total += n
        print(f"{ratio:5.1%} {n:5d}  {ra}/{pa}  ~  {rb}/{pb}")
    print(f"\n{len(pairs)} near-identical pairs (>= {a.min:.0%}), {total} lines held twice")
    return 1 if (a.strict and pairs) else 0


if __name__ == "__main__":
    sys.exit(main())
