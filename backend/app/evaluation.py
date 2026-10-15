import re


def score_case(case: dict, response: dict) -> dict:
    answer = response.get("answer", "").casefold()
    phrases = case.get("expected_phrases", [])
    phrase_hits = sum(phrase.casefold() in answer for phrase in phrases)
    citations = response.get("citations", [])
    cited_files = [citation.get("filename", "").casefold() for citation in citations]
    source_hit = not case.get("expected_source") or any(
        case["expected_source"].casefold() in name for name in cited_files
    )
    cited_numbers = {citation.get("number") for citation in citations}
    answer_numbers = {
        int(number) for number in re.findall(r"\[(\d+)\]", response.get("answer", ""))
    }
    citations_valid = (
        bool(response.get("abstained"))
        if not phrases
        else bool(cited_numbers) and cited_numbers.issubset(answer_numbers)
    )
    return {
        "source_hit": source_hit,
        "phrase_recall": (
            phrase_hits / len(phrases)
            if phrases
            else (1.0 if response.get("abstained") else 0.0)
        ),
        "citations_valid": citations_valid,
        "abstained": bool(response.get("abstained")),
    }


def summarize(results: list[dict]) -> dict:
    if not results:
        return {
            "cases": 0,
            "source_recall_at_k": 0.0,
            "answer_phrase_recall": 0.0,
            "citation_validity": 0.0,
        }
    count = len(results)
    return {
        "cases": count,
        "source_recall_at_k": round(
            sum(result["source_hit"] for result in results) / count, 3
        ),
        "answer_phrase_recall": round(
            sum(result["phrase_recall"] for result in results) / count, 3
        ),
        "citation_validity": round(
            sum(result["citations_valid"] for result in results) / count, 3
        ),
    }
