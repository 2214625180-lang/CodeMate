#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from app.services.mcp_compliance_service import assess_mcp_compliance


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CodeMate MCP compliance controls")
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = assess_mcp_compliance(include_runtime=args.runtime)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["status"] != "compliant":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
