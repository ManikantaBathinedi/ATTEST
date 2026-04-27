"""JUnit XML report generator.

Creates a JUnit XML file from ATTEST RunSummary.
This format is understood by all CI/CD systems:
  - GitHub Actions
  - Azure DevOps
  - Jenkins
  - GitLab CI

Usage:
    attest run  → auto-generates reports/junit.xml
"""

from __future__ import annotations

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring, ElementTree

from attest.core.models import RunSummary, Status


def generate_junit_xml(
    summary: RunSummary,
    output_path: str,
) -> None:
    """Generate a JUnit XML report.

    Args:
        summary: The test run results.
        output_path: Where to save the XML file.
    """
    # Root element
    testsuites = Element("testsuites")
    testsuites.set("name", "ATTEST")
    testsuites.set("tests", str(summary.total))
    testsuites.set("failures", str(summary.failed))
    testsuites.set("errors", str(summary.errors))
    testsuites.set("time", f"{summary.duration_seconds:.2f}")

    # Group results by suite
    suites: dict = {}
    for r in summary.results:
        suite_name = r.suite or "default"
        if suite_name not in suites:
            suites[suite_name] = []
        suites[suite_name].append(r)

    # Create testsuite elements
    for suite_name, results in suites.items():
        suite_el = SubElement(testsuites, "testsuite")
        suite_el.set("name", suite_name)
        suite_el.set("tests", str(len(results)))
        suite_el.set("failures", str(sum(1 for r in results if r.status == Status.FAILED)))
        suite_el.set("errors", str(sum(1 for r in results if r.status == Status.ERROR)))
        suite_time = sum(r.duration_ms for r in results) / 1000
        suite_el.set("time", f"{suite_time:.2f}")

        for r in results:
            testcase = SubElement(suite_el, "testcase")
            testcase.set("name", r.scenario)
            testcase.set("classname", suite_name)
            testcase.set("time", f"{r.duration_ms / 1000:.2f}")

            # Add scores as system-out
            if r.scores:
                scores_text = " | ".join(
                    f"{name}: {s.score:.2f}" for name, s in r.scores.items()
                )
                sysout = SubElement(testcase, "system-out")
                sysout.text = scores_text

            # Add failure details
            if r.status == Status.FAILED:
                failed_assertions = [a for a in r.assertions if not a.passed]
                failed_scores = [s for s in r.scores.values() if not s.passed]

                messages = []
                for a in failed_assertions:
                    messages.append(f"{a.name}: {a.message}")
                for s in failed_scores:
                    messages.append(f"{s.name}: score {s.score:.2f} below threshold {s.threshold}")

                failure = SubElement(testcase, "failure")
                failure.set("message", "; ".join(messages) or "Test failed")
                failure.text = "\n".join(messages)

            # Add error details
            if r.status == Status.ERROR:
                error = SubElement(testcase, "error")
                error.set("message", r.error or "Unknown error")
                error.text = r.error

    # Write to file
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tree = ElementTree(testsuites)
    tree.write(str(path), encoding="unicode", xml_declaration=True)
