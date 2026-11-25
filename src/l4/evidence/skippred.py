"""Does the skip of an old test predate the unit? (skipped-test-hold D1, L4-VER-092)

The pure part of the rule: the two sources of one test file and the paths the unit changed go in, a decision comes out.
`l4.evidence.collect.skip_predating` reads the blobs from git and calls it. The rule compares the skip constructs of
the file at the base and at the head (`scan.skip_constructs`); it runs no test and reads no base report.
"""

from collections.abc import Collection

from l4.config.schema import L4Config
from l4.security.protected import glob_match
from l4.verifier import scan

MODULE = "<module>"


def qualified_name(test_id: str, path: str) -> str | None:
    """The `Name` or `Class.name` of a JUnit id in the file `path` (`tests.test_a.TestK::test_x[1]` in `tests/test_a.py`
    is `TestK.test_x`); None when the id is not one of those two shapes (a nested class, a path that does not fit)."""
    classname, sep, name = test_id.partition("::")
    function = name.split("[", 1)[0]
    if not sep or not function or not path.endswith(".py"):
        return None
    parts = classname.split(".")
    for modules in range(len(parts), 0, -1):
        module = "/".join(parts[:modules]) + ".py"
        if path == module or path.endswith("/" + module):
            classes = parts[modules:]
            if len(classes) > 1:
                return None
            return f"{classes[0]}.{function}" if classes else function
    return None


def _scopes_of(qualname: str, head: str) -> set[str]:
    """The scopes whose skip constructs can skip `qualname`: itself, its class, the module and every function or method
    of the file that is not a test (a fixture, a helper, `setUp`): the tests share those."""
    scopes = {qualname, MODULE}
    if "." in qualname:
        scopes.add(qualname.split(".", 1)[0])
    scopes |= {f for f in scan.function_names(head) if not f.rsplit(".", 1)[-1].startswith("test")}
    return scopes


def skip_predates(base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config) -> bool:
    """True when the unit added or changed no skip that can affect the test `qualname` of a file whose text is `base`
    at the base and `head` at the head. Every doubt is False (the skip stays a deterministic finding): a source that
    does not parse, a test that was not there at the base, a construct added in a scope that can skip it, and (a skip
    with no construct in the file, so it comes from outside) a changed test-support or runner-configuration file."""
    before, after = scan.skip_constructs(base), scan.skip_constructs(head)
    if before is None or after is None or qualname not in scan.defined_tests(base):
        return False
    scopes = _scopes_of(qualname, head)
    if any(scope in scopes for scope, _ in after - before):  # a multiset difference: a removed skip never counts
        return False
    if any(scope in scopes for scope, _ in after):
        return True
    outside = (*cfg.tdd.test_support_globs, *cfg.tdd.runner_config_files)
    return not any(glob_match(g, p) for p in changed for g in outside)
