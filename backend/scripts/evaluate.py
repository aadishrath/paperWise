import argparse
import json
from pathlib import Path

import httpx

from app.evaluation import score_case, summarize


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run PaperWise's small local RAG evaluation set."
    )
    parser.add_argument(
        "--api", default="http://localhost:8000", help="PaperWise API base URL"
    )
    args = parser.parse_args()
    cases = json.loads(
        (Path(__file__).parents[1] / "evaluation" / "cases.json").read_text(
            encoding="utf-8"
        )
    )
    results = []
    with httpx.Client(timeout=240.0) as client:
        for index, case in enumerate(cases, start=1):
            response = client.post(
                f"{args.api.rstrip('/')}/api/chat", json={"question": case["question"]}
            )
            response.raise_for_status()
            result = score_case(case, response.json())
            results.append(result)
            print(f"{index}. {case['question']} — {result}")
    print(json.dumps(summarize(results), indent=2))


if __name__ == "__main__":
    main()
