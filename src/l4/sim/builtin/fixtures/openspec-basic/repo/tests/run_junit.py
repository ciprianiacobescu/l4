"""The test gate of the simulation fixtures: stdlib `unittest`, reported as the JUnit file the harness reads.

The vendored harness installs no dev dependencies, so there is no pytest here. Ids are `classname::name`; a test module
that does not import is a collection failure (a `testcase` with no class and an `error` saying so).
"""

import sys
import traceback
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / ".l4-out" / "junit.xml"
MAX_MESSAGE = 500


class Recorder(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.cases: list[ET.Element] = []

    def _case(self, test: unittest.TestCase) -> ET.Element:
        module_and_class, _, name = test.id().rpartition(".")
        if type(test).__name__ == "_FailedTest":  # the module failed to import: `name` is the module
            case = ET.Element("testcase", name=name)
        else:
            case = ET.Element("testcase", classname=module_and_class, name=name)
        self.cases.append(case)
        return case

    def _problem(self, test: unittest.TestCase, tag: str, err: tuple) -> None:
        case = self._case(test)
        if type(test).__name__ == "_FailedTest":
            ET.SubElement(case, "error", message="collection failure")
            return
        message = "".join(traceback.format_exception_only(err[0], err[1])).strip()[:MAX_MESSAGE]
        ET.SubElement(case, tag, message=message)

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self._case(test)

    def addFailure(self, test: unittest.TestCase, err: tuple) -> None:
        super().addFailure(test, err)
        self._problem(test, "failure", err)

    def addError(self, test: unittest.TestCase, err: tuple) -> None:
        super().addError(test, err)
        self._problem(test, "failure", err)  # pytest writes a raised exception as a failure too

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        ET.SubElement(self._case(test), "skipped", message=reason[:MAX_MESSAGE])


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    tests = ROOT / "tests"
    suite = unittest.defaultTestLoader.discover(str(tests), pattern="test_*.py", top_level_dir=str(tests))
    result = Recorder()
    suite.run(result)
    root = ET.Element("testsuites")
    problems = len(result.failures) + len(result.errors)
    counts = {"tests": len(result.cases), "failures": problems, "skipped": len(result.skipped)}
    suite_element = ET.SubElement(root, "testsuite", name="unittest", **{k: str(v) for k, v in counts.items()})
    suite_element.extend(result.cases)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(REPORT, encoding="utf-8", xml_declaration=True)
    print(f"{len(result.cases)} tests, {problems} problems", file=sys.stderr)
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
