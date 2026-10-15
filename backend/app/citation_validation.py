import re


CITATION_RE = re.compile(r"\[(\d+)\]")


class InvalidCitations(ValueError):
    pass


def cited_passages(answer: str, passages: list[dict]) -> list[dict]:
    references = [int(number) for number in CITATION_RE.findall(answer)]
    if not references:
        raise InvalidCitations("Answer did not include a verifiable source citation.")
    if any(number < 1 or number > len(passages) for number in references):
        raise InvalidCitations("Answer referenced a source that was not retrieved.")

    cited = []
    for number in dict.fromkeys(references):
        cited.append({**passages[number - 1], "citation_number": number})
    return cited
