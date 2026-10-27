"""Self-check for check_clauses.py, check_includes.py and find_copies.py on a
throwaway repo. Run: python tooling/test_checks.py"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script, *args):
    r = subprocess.run([sys.executable, "-I", os.path.join(HERE, script), *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


with tempfile.TemporaryDirectory() as tmp:
    a = os.path.join(tmp, "repoA")
    b = os.path.join(tmp, "repoB")
    os.makedirs(os.path.join(a, ".git"))
    write(a, "docs/features/S5-x.md", "- **S5.1** one\n- **S5.2** two\n- **S5.10** ten\n")
    write(a, "tests/unit/t/main.c", "ZTEST(x, test_s5_01_a) {}\nZTEST(x, test_s5_100_z) {}\n")
    write(a, "src/state/sm.c", '#include "codec.h"\n#include "../led/led.h"\n#include "fs_internal.h"\n'
          '/* #include "main.h" */\n#if 0\n#include "main.h"\n#endif\n')
    write(a, "src/data/codec.h", "")
    write(a, "src/led/led.h", "")
    write(a, "src/fs/fs_internal.h", "")
    write(a, "src/fs/fs.c", '#include "fs_internal.h"\n')
    write(a, "src/main.h", "")
    write(a, "src/main.c", '#include "main.h"\n')
    write(a, "src/x/x.c", '#include "dup.h"\n#include "mine.h"\n')
    write(a, "src/x/mine.h", "")
    write(a, "src/y/mine.h", "")
    write(a, "src/y/dup.h", "")
    write(a, "src/z/dup.h", "")
    write(a, "src/z/z.c", '#include "main.h"\n')
    write(a, "rules.txt", "state !-> data\n* !-> main\n")
    write(b, "src/data/codec.h", "")
    same = "".join(f"line {i}\n" for i in range(50))
    write(a, "src/data/queue.c", same)
    write(b, "src/data/queue.c", same.replace("line 3\n", "line three\n"))
    write(b, "src/other/thing.c", "".join(f"x {i}\n" for i in range(50)))
    write(a, "src/other/thing.c", "".join(f"y {i}\n" for i in range(50)))

    rc, out = run("check_clauses.py", os.path.join(a, "docs/features/S5-x.md"), "--strict")
    assert rc == 1 and "S5.2     GAP" in out and "S5.1     tests" in out, out
    assert "S5.10    GAP" in out, "s5_100 must not count as S5.10: " + out
    assert "1/3 clauses covered" in out, out

    rc, out = run("check_includes.py", a, "--rules", os.path.join(a, "rules.txt"), "--strict")
    assert rc == 1, out
    body = out.split("\n\n")[0]
    assert "state -> data" in body and "private header" in body, out
    assert "led" not in body, "../led/led.h is allowed: " + out
    assert "sm.c:4" not in body and "sm.c:6" not in body, "commented and #if 0 includes must be ignored: " + out
    assert "z -> main" in body, "* !-> main must fire for z.c: " + out
    assert "x.c:1" in body and "ambiguous" in body, out
    assert "x.c:2" not in body, "mine.h in the including dir wins over the other module: " + out
    assert "4 include violations" in out, out
    rc, out = run("check_includes.py", a, "--rules", os.path.join(a, "rules.txt"))
    assert rc == 0, "without --strict the check is advisory"

    rc, out = run("find_copies.py", a, b, "--min", "0.9", "--strict")
    assert rc == 1 and "queue.c" in out and "thing.c" not in out and "1 near-identical pairs" in out, out
    rc, out = run("find_copies.py", a, b, "--min", "0.999")
    assert rc == 0 and "0 near-identical pairs" in out, out

print("test_checks: ok")
