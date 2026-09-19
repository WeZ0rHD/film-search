"""Build: compile check + catalog.db + unit tests. Writes data/build.json."""
import os
import sys
import json
import py_compile
import time
import io
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


def main():
    t0 = time.time()
    for fn in ("film_search.py", "providers.py", "server.py", "run_acceptance.py",
               "run_benchmark.py", "run_runtime_proof.py"):
        py_compile.compile(os.path.join(BASE, fn), doraise=True)
        print(f"compile OK {fn}", flush=True)
    import providers as prov
    info = prov.build_catalog_db()
    print(f"catalog.db {info}", flush=True)
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(BASE, "tests"), pattern="test_*.py")
    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=1)
    result = runner.run(suite)
    print(buf.getvalue()[-2000:], flush=True)
    tests_ok = result.wasSuccessful()
    receipt = {"ok": tests_ok, "catalog_db": info, "seconds": round(time.time() - t0, 1),
               "ran": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}
    with open(os.path.join(BASE, "data", "build.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=1)
    print("BUILD_" + ("OK" if tests_ok else "FAIL"), flush=True)
    return 0 if tests_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
