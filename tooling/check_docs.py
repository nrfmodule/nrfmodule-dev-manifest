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
anywhere; a name that is also a C identifier (an enum value) is not Kconfig.
A path is looked up next to the doc, from the repo root, as a path suffix of
any tracked file in the repo, an --also root or the NCS tree, and as
<repo name>/<path> for any repo in the workspace or under modules/lib.
Historical records are skipped: CHANGELOG, docs/field-tests, docs/adr,
.claude/handoffs and any file with a date in its name.

usage: check_docs.py REPO [--also DIR ...] [--ncs DIR] [--strict]

--also adds repos whose files and symbols the docs may cite without a repo
prefix (default: nrfmodule-sdk and nrfmodule-core under --ncs, and this
manifest). --ncs is the NCS workspace (default c:/ncs/nrfmodule_v3x).
--strict exits 1 on any finding.
"""
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
NCS_FILE_DIRS = ("zephyr", "nrf", "nrfxlib", "ncs-serial-modem", "modules/lib")
NCS_HEADER_DIRS = ("zephyr/include", "nrf/include", "nrfxlib")
MANIFEST = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tracked(root):
    try:
        out = subprocess.run(["git", "-C", root, "ls-files"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [p for p in out.splitlines() if p]


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


def other_repos(ncs):
    """Repos a doc may cite by name (nRFTrackerFW/docs/x.md): workspace siblings and NCS modules."""
    roots = [os.path.join(os.path.dirname(MANIFEST), d) for d in os.listdir(os.path.dirname(MANIFEST))]
    libs = os.path.join(ncs, "modules", "lib")
    roots += [os.path.join(libs, d) for d in os.listdir(libs)] if os.path.isdir(libs) else []
    roots.append(os.path.join(ncs, "ncs-serial-modem"))
    return [r for r in roots if os.path.exists(os.path.join(r, ".git"))]


def index(repo, also, ncs):
    """Return (kconfig names, citable paths, source identifiers)."""
    kconfig, paths, idents = set(), set(), set()
    for root in [repo] + also:
        for rel in tracked(root):
            add_suffixes(paths, rel)
            full = os.path.join(root, rel)
            name = rel.rsplit("/", 1)[-1]
            if name.startswith("Kconfig"):
                kconfig |= kconfig_names(read(full))
            elif name.endswith(SOURCE_EXT) or name == "CMakeLists.txt":
                idents.update(IDENT_RE.findall(read(full)))
    for root in other_repos(ncs):
        for rel in tracked(root):
            add_prefixes(paths, os.path.basename(root) + "/" + rel)
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


def doc_files(repo):
    docs = [p for p in tracked(repo) if p.endswith(".md")]
    docs += [p for p in UNTRACKED_DOCS if p not in docs and os.path.isfile(os.path.join(repo, p))]
    return [p for p in docs if not SKIP_DOC.search(p)]


def check(repo, kconfig, paths, idents):
    findings = []
    for rel in doc_files(repo):
        in_fence = False
        for n, line in enumerate(read(os.path.join(repo, rel)).split("\n"), 1):
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            where = f"{rel}:{n}"
            for name in KCONFIG_REF_RE.findall(line):
                if name not in kconfig and "CONFIG_" + name not in idents:
                    findings.append(f"{where}: kconfig CONFIG_{name} is not defined")
            if in_fence:
                continue
            for tok in SPAN_RE.findall(line):
                tok = tok.strip()
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
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    repo = os.path.abspath(a.repo)
    if a.also is None:
        near = [os.path.join(a.ncs, "modules/lib", n) for n in ("nrfmodule-sdk", "nrfmodule-core")] + [MANIFEST]
        a.also = [p for p in near if os.path.isdir(p) and os.path.abspath(p) != repo]
    kconfig, paths, idents = index(repo, [os.path.abspath(p) for p in a.also], a.ncs)
    findings = check(repo, kconfig, paths, idents)
    for f in findings:
        print(f)
    print(f"\n{len(findings)} doc drift findings in {len(doc_files(repo))} docs")
    return 1 if (a.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
