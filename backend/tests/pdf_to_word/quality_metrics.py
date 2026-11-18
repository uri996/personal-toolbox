"""Reference-aware OCR metrics. Whitespace is ignored only in model scoring.

Pipeline fidelity tests separately compare exact paragraph strings, including
spaces, full-width characters and punctuation.
"""

from dataclasses import dataclass


def compact(text):
    return "".join(text.split())


@dataclass(frozen=True)
class CharacterErrors:
    substitutions: int
    deletions: int
    insertions: int
    expected: int

    @property
    def cer(self):
        return (self.substitutions + self.deletions + self.insertions) / max(self.expected, 1)


def character_errors(expected: str, actual: str) -> CharacterErrors:
    # Each cell contains distance and the corresponding S/D/I counts. Rolling
    # rows keep the multi-page comparison linear in memory.
    previous = [(index, 0, 0, index) for index in range(len(actual) + 1)]
    for row, left in enumerate(expected, 1):
        current = [(row, 0, row, 0)]
        for column, right in enumerate(actual, 1):
            distance, substitutions, deletions, insertions = previous[column - 1]
            substitution = (distance + (left != right), substitutions + (left != right), deletions, insertions)
            distance, substitutions, deletions, insertions = previous[column]
            deletion = (distance + 1, substitutions, deletions + 1, insertions)
            distance, substitutions, deletions, insertions = current[-1]
            insertion = (distance + 1, substitutions, deletions, insertions + 1)
            current.append(min(substitution, deletion, insertion, key=lambda item: item[0]))
        previous = current
    _, substitutions, deletions, insertions = previous[-1]
    return CharacterErrors(substitutions, deletions, insertions, len(expected))


def contiguous_line_error(expected: str, actual: str) -> float:
    """Edit distance to one contiguous substring, with insertions penalized."""
    previous = [0] * (len(actual) + 1)
    for row, left in enumerate(expected, 1):
        current = [row]
        for column, right in enumerate(actual, 1):
            current.append(min(previous[column - 1] + (left != right), previous[column] + 1, current[-1] + 1))
        previous = current
    return min(previous) / max(len(expected), 1)


def missing_lines(expected: list[str], actual: str) -> list[str]:
    return [line for line in expected if compact(line) not in compact(actual)]
