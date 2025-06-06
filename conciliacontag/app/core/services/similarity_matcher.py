from difflib import SequenceMatcher

def similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

class SimilarityMatcher:
    def match(self, a: str, b: str) -> float:
        return similaridade(a, b) 