#!/usr/bin/env python3
"""Doc drift check for one repo.

Reads the repo's tracked Markdown files plus an untracked CLAUDE.md,
.claude/CLAUDE.md or CONTEXT.md, and reports names the docs cite that no
longer exist:

    kconfig   CONFIG_X or SB_CONFIG_X with no `config X` in any Kconfig file
    path      `src/foo.c`, `docs/x.md`, `src/state/` with no such file or dir
    function  `foo_bar()` with no foo_bar in any source file

Paths and functions count only inside inline code spans, outside fenced
blocks. A path must end in a file extension or "/". Kconfig names count
anywhere; a name that is also part of a C identifier (the enum value
EVT_CONFIG_OK cited as CONFIG_OK) is not Kconfig.
A path is looked up next to the doc, from the repo root, as a path suffix of
any tracked file in the repo, an --also root or the NCS tree, and as
<repo name>/<path> for any of those repos. Historical records are skipped:
CHANGELOG, docs/field-tests, docs/adr, .claude/handoffs and any file with a
date in its name.

The rules file skips docs or single names the checker cannot judge, such as
a doc about another codebase:

    # comment
    docs/display_protocol.md              # skip the whole doc (fnmatch glob)
    README.md workspace/modules/lib/      # skip one name in one doc

usage: check_docs.py REPO [--also DIR ...] [--ncs DIR] [--rules FILE] [--strict]

--also replaces the repos whose files and symbols count as existing (default:
every git repo next to this manifest, under --ncs/modules/lib and
ncs-serial-modem, except a checkout of REPO itself). --ncs is the NCS
workspace (default c:/ncs/nrfmodule_v3x). --rules defaults to
tooling/docs_rules/<repo name>.txt next to this script. --strict exits 1 on
any finding.
"""
import fnmatch
import argparse
import os
import re
import subprocess
import sys

KCONFIG_REF_RE = re.compile(r"\b(?:SB_)?CONFIG_([A-Z0-9][A-Z0-9_]*[A-Z0-9])\b")
KCONFIG_DEF_RE = re.compile(r"^\s*(?:menu)?config\s+([A-Za-z0-9_]+)", re.M)
KCONFIG_LOG_RE = re.compile(r"^\s*module\s*=\s*([A-Za-z0-9_]+)", re.M)
LOG_LEVELS = ("", "_OFF", "_ERR", "_WRN", "_INF", "_DBG", "_DEFAULT")
SPAN_RE = re.compile(r"`([^`\n]+)`")
FUNC_RE = re.compile(r"^([A-Za-z_]\w*)\(\)$")
PATH_RE = re.compile(r"^[\w./-]*?[\w-]+(\.(c|h|py|conf|overlay|yaml|yml|cmake|txt|md|dts|dtsi|sh|ps1|json|csv|html)|/)$")
SOURCE_EXT = (".c", ".h", ".cpp", ".hpp", ".py", ".cmake", ".ld", ".S", ".sh", ".ps1")
SKIP_DOC = re.compile(r"(^|/)(CHANGELOG[^/]*|docs/field-tests/.*|docs/adr/.*|\.claude/handoffs/.*|[^/]*\d{4}-\d\d-\d\d[^/]*)$",
                      re.I)
UNTRACKED_DOCS = ("CLAUDE.md", ".claude/CLAUDE.md", "CONTEXT.md")
IDENT_RE = re.compile(r"[A-Za-z_]\w*")
NCS_KCONFIG_DIRS = ("zephyr", "nrf", "bootloader", "nrfxlib", "modules", "ncs-serial-modem")
NCS_FILE_DIRS = ("zephyr", "nrf", "nrfxlib", "ncs-serial-modem", "modules/lib", "modules/hal/st")
NCS_HEADER_DIRS = ("zephyr/include", "nrf/include", "nrfxlib")
MANIFEST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_lines(root, *args):
    try:
        out = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.splitlines() if p]


def tracked(root):
    return git_lines(root, "ls-files") or []


def published(root):
    """Files on origin/main, so a sibling checkout that is behind still counts what is merged."""
    return git_lines(root, "ls-tree", "-r", "--name-only", "origin/main") or tracked(root)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def walk(root, keep):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".") and d != "build"]
        for f in fns:
            if keep(f):
                yield os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")


def add_suffixes(paths, rel):
    """rel and every parent dir, each with all its leading dirs dropped in turn."""
    parts = rel.split("/")
    for end in range(1, len(parts) + 1):
        for start in range(end):
            paths.add("/".join(parts[start:end]))


def add_prefixes(paths, rel):
    parts = rel.split("/")
    for end in range(1, len(parts) + 1):
        paths.add("/".join(parts[:end]))


def kconfig_names(text):
    names = set(KCONFIG_DEF_RE.findall(text))
    for mod in KCONFIG_LOG_RE.findall(text):
        names.update(mod + "_LOG_LEVEL" + lvl for lvl in LOG_LEVELS)
    return names


def repo_name(repo):
    """Basename of the main checkout, so a worktree of a repo has the repo's name."""
    try:
        common = subprocess.run(["git", "-C", repo, "rev-parse", "--git-common-dir"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.path.basename(repo)
    common = common if os.path.isabs(common) else os.path.join(repo, common)
    return os.path.basename(os.path.dirname(os.path.abspath(common)))


def other_repos(ncs, repo):
    """Workspace siblings and NCS modules, except any checkout of repo itself."""
    roots = [os.path.join(os.path.dirname(MANIFEST), d) for d in os.listdir(os.path.dirname(MANIFEST))]
    libs = os.path.join(ncs, "modules", "lib")
    roots += [os.path.join(libs, d) for d in os.listdir(libs)] if os.path.isdir(libs) else []
    roots.append(os.path.join(ncs, "ncs-serial-modem"))
    own = repo_name(repo)
    return [r for r in roots if os.path.exists(os.path.join(r, ".git")) and repo_name(r) != own]


def index(repo, also, ncs):
    """Return (kconfig names, citable paths, source identifiers)."""
    kconfig, paths, idents = set(), set(), set()
    for root in [repo] + also:
        prefix = repo_name(root) + "/"
        if root != repo:
            for rel in published(root):
                add_suffixes(paths, rel)
                add_prefixes(paths, prefix + rel)
        for rel in tracked(root):
            add_suffixes(paths, rel)
            add_prefixes(paths, prefix + rel)
            full = os.path.join(root, rel)
            name = rel.rsplit("/", 1)[-1]
            if name.startswith("Kconfig"):
                kconfig |= kconfig_names(read(full))
            elif name.endswith(SOURCE_EXT) or name == "CMakeLists.txt":
                idents.update(IDENT_RE.findall(read(full)))
    for d in NCS_FILE_DIRS:
        for rel in walk(os.path.join(ncs, d), lambda n: True):
            add_suffixes(paths, d + "/" + rel)
    for d in NCS_KCONFIG_DIRS:
        for rel in walk(os.path.join(ncs, d), lambda n: n.startswith("Kconfig")):
            kconfig |= kconfig_names(read(os.path.join(ncs, d, rel)))
    for d in NCS_HEADER_DIRS:
        for rel in walk(os.path.join(ncs, d), lambda n: n.endswith(".h")):
            idents.update(IDENT_RE.findall(read(os.path.join(ncs, d, rel))))
    return kconfig, paths, idents


def is_path(tok):
    if tok.startswith(("http", "~", "-", "/")) or "/build/" in tok or tok.startswith("build/"):
        return False
    return PATH_RE.match(tok) is not None


def path_exists(tok, doc_dir, repo, paths):
    if os.path.exists(os.path.join(doc_dir, tok)) or os.path.exists(os.path.join(repo, tok)):
        return True
    rel = tok.rstrip("/")
    while rel.startswith(("./", "../")):
        rel = rel.split("/", 1)[1]
    return rel in paths


def load_rules(path):
    """Return [(doc glob, name or None)]; None skips the whole doc."""
    rules = []
    for line in read(path).split("\n") if path and os.path.isfile(path) else []:
        fields = line.split("#", 1)[0].split()
        if fields:
            rules.append((fields[0], fields[1] if len(fields) > 1 else None))
    return rules


def doc_files(repo, rules=()):
    docs = [p for p in tracked(repo) if p.endswith(".md")]
    docs += [p for p in UNTRACKED_DOCS if p not in docs and os.path.isfile(os.path.join(repo, p))]
    skipped = [g for g, name in rules if name is None]
    return [p for p in docs if not SKIP_DOC.search(p) and not any(fnmatch.fnmatch(p, g) for g in skipped)]


def check(repo, kconfig, paths, idents, rules=()):
    enum_tails = {i.split("CONFIG_", 1)[1] for i in idents if "CONFIG_" in i}
    findings = []
    for rel in doc_files(repo, rules):
        allowed = {name for g, name in rules if name and fnmatch.fnmatch(rel, g)}
        in_fence = False
        for n, line in enumerate(read(os.path.join(repo, rel)).split("\n"), 1):
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            where = f"{rel}:{n}"
            for name in KCONFIG_REF_RE.findall(line):
                if name not in kconfig and name not in enum_tails and "CONFIG_" + name not in allowed:
                    findings.append(f"{where}: kconfig CONFIG_{name} is not defined")
            if in_fence:
                continue
            for tok in SPAN_RE.findall(line):
                tok = tok.strip()
                if tok in allowed:
                    continue
                m = FUNC_RE.match(tok)
                if m:
                    if m.group(1) not in idents:
                        findings.append(f"{where}: function {tok} is not in any source file")
                elif is_path(tok) and not path_exists(tok, os.path.dirname(os.path.join(repo, rel)), repo, paths):
                    findings.append(f"{where}: path {tok} does not exist")
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo")
    ap.add_argument("--also", action="append")
    ap.add_argument("--ncs", default="c:/ncs/nrfmodule_v3x")
    ap.add_argument("--rules")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    also = a.also if a.also is not None else other_repos(a.ncs, repo)
    rules_path = a.rules or os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs_rules",
                                         repo_name(repo) + ".txt")
    rules = load_rules(rules_path)
    kconfig, paths, idents = index(repo, [os.path.abspath(p) for p in also], a.ncs)
    findings = check(repo, kconfig, paths, idents, rules)
    for f in findings:
        print(f)
    print(f"\n{len(findings)} doc drift findings in {len(doc_files(repo, rules))} docs, {len(rules)} rules")
    return 1 if (a.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
