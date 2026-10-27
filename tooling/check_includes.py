#!/usr/bin/env python3
"""Include-direction check for one repo.

A module is the first directory under the source root (src/state, src/data,
...; for the SDK, lib/modem, lib/avirings, ...). Every quoted include in a
.c/.h file is resolved to the module that owns the header, then checked
against the repo's rules file:

    # comment
    state !-> data, collector      # state may not include data or collector
    * !-> main                     # nobody includes main

Two rules need no file: a header named *_internal.h or *_priv.h may only be
included from its own module, and a quoted header that resolves to two
different modules is reported as ambiguous. Angle-bracket includes are
external and ignored.

usage: check_includes.py REPO [--rules FILE] [--src DIR] [--strict]

--rules defaults to tooling/include_rules/<repo basename>.txt next to this
script; without a rules file only the built-in rules run. --src defaults to
src (or lib when src is missing). --strict exits 1 on any violation.
"""
import argparse
import os
import re
import sys

INC_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.M)
PRIVATE_RE = re.compile(r"_(internal|priv)\.h$")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
SRC_EXT = (".c", ".h", ".cpp", ".hpp")


def strip_inactive(text):
    """Blank block comments and #if 0 regions, keeping newlines so line numbers hold."""
    text = BLOCK_COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    out, depth = [], 0
    for line in text.split("\n"):
        s = line.strip()
        if depth:
            if re.match(r"#\s*if(n?def)?\b", s):
                depth += 1
            elif re.match(r"#\s*endif\b", s):
                depth -= 1
            out.append("")
            continue
        if re.match(r"#\s*if\s+0\b", s):
            depth = 1
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def repo_name(repo):
    """Basename of the main checkout, so a worktree finds the same rules file."""
    try:
        import subprocess
        common = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"], capture_output=True,
                                text=True, check=True).stdout.strip()
        common = common if os.path.isabs(common) else os.path.join(repo, common)
        return os.path.basename(os.path.dirname(os.path.abspath(common)))
    except (OSError, subprocess.CalledProcessError):
        return os.path.basename(repo)


def load_rules(path):
    rules = []
    if not path or not os.path.isfile(path):
        return rules
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if "!->" not in line:
                sys.exit(f"{path}:{n}: expected 'A !-> B, C'")
            src, dst = (s.strip() for s in line.split("!->", 1))
            rules.append((src, [d.strip() for d in dst.split(",") if d.strip()], n))
    return rules


def module_of(path, root):
    rel = os.path.relpath(path, root).replace("\\", "/")
    parts = rel.split("/")
    return parts[0] if len(parts) > 1 else os.path.splitext(parts[0])[0]  # src/main.c -> "main"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo")
    ap.add_argument("--rules")
    ap.add_argument("--src")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    src = os.path.join(repo, a.src) if a.src else next(
        (os.path.join(repo, d) for d in ("src", "lib") if os.path.isdir(os.path.join(repo, d))), None)
    if not src or not os.path.isdir(src):
        sys.exit(f"no source dir under {repo} (tried src, lib; use --src)")
    rules_path = a.rules or os.path.join(os.path.dirname(os.path.abspath(__file__)), "include_rules",
                                         repo_name(repo) + ".txt")
    rules = load_rules(rules_path)

    files = []
    for dp, _, fns in os.walk(src):
        files += [os.path.join(dp, f) for f in fns if f.endswith(SRC_EXT)]
    owners = {}  # basename -> set of modules that own a header with that name
    for f in files:
        if f.endswith((".h", ".hpp")):
            owners.setdefault(os.path.basename(f), set()).add(module_of(f, src))

    violations = []
    for f in files:
        mod = module_of(f, src)
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                text = strip_inactive(fh.read())
        except OSError:
            continue
        for m in INC_RE.finditer(text):
            inc = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            where = f"{os.path.relpath(f, repo)}:{line}"
            # Preprocessor order: the including file's directory first, then the
            # source root; a bare name not found there is looked up by owner.
            local = os.path.normpath(os.path.join(os.path.dirname(f), inc))
            rooted = os.path.normpath(os.path.join(src, inc))
            if os.path.isfile(local):
                dst = {module_of(local, src)}
            elif os.path.isfile(rooted):
                dst = {module_of(rooted, src)}
            elif "/" in inc:
                dst = set()
            else:
                dst = owners.get(inc, set())
            if not dst:
                continue  # generated or external header, not ours to judge
            if len(dst) > 1:
                violations.append(f"{where}: \"{inc}\" is ambiguous, owned by {sorted(dst)}")
                continue
            to = next(iter(dst))
            if to == mod:
                continue
            if PRIVATE_RE.search(inc):
                violations.append(f"{where}: {mod} includes private header \"{inc}\" of {to}")
            for rsrc, rdsts, n in rules:
                if rsrc in ("*", mod) and any(d in ("*", to) for d in rdsts):
                    violations.append(f"{where}: {mod} -> {to} (\"{inc}\") denied by {os.path.basename(rules_path)}:{n}")

    for v in violations:
        print(v)
    print(f"\n{len(violations)} include violations in {len(files)} files, {len(rules)} rules from "
          f"{rules_path if rules else 'built-ins only'}")
    return 1 if (a.strict and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
