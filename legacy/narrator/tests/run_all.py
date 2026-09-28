"""Run every suite, reporting one line each."""
import glob, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
# Needs the network (it really installs a package), so it is skippable.
SLOW = {"test_components.py"}


def main(argv):
    quick = "--quick" in argv
    env = dict(os.environ,
               PYTHONPATH=os.pathsep.join(
                   [os.path.join(HERE, "stubs"), os.path.dirname(HERE), HERE]))
    suites = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    suites += sorted(glob.glob(os.path.join(HERE, "gui_smoke*.py")))
    failed, skipped = [], []
    for path in suites:
        name = os.path.basename(path)
        if quick and name in SLOW:
            skipped.append(name)
            continue
        started = time.time()
        proc = subprocess.run([sys.executable, path], capture_output=True,
                              text=True, env=env, cwd=HERE, timeout=1800)
        tail = [l for l in proc.stdout.splitlines() if l.strip()]
        status = "ok  " if proc.returncode == 0 else "FAIL"
        if proc.returncode != 0:
            failed.append(name)
        print(f"{status} {time.time() - started:6.1f}s  {name:<28} "
              f"{tail[-1][:70] if tail else ''}")
        if proc.returncode != 0:
            print("      " + (proc.stderr.strip().splitlines() or ["?"])[-1][:100])
    print(f"\n{len(suites) - len(failed) - len(skipped)} passed, "
          f"{len(failed)} failed"
          + (f", {len(skipped)} skipped" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
