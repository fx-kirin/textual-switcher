import unicodedata
from curses.ascii import isprint
from rapidfuzz import fuzz


def filter_printable(string):
    if isinstance(string, str):
        result = unicodedata.normalize('NFKD', string)
    else:
        result = string.decode('utf8')
    return result


class ListFilter(object):
    def __init__(self):
        self._search_key = ""

    def update_search_key(self, search_key):
        self._search_key = self._normalize(search_key)

    def _normalize(self, title):
        title = filter_printable(title)
        try:
            for c in [" ", "\n", "\t"]:
                title = title.replace(c, "")
        except:
            breakpoint()
        title = title.lower()
        return title

    def get_candidate_score(self, candidate):
        if not self._search_key:
            return 100
        candidate = self._normalize(candidate)
        if candidate in self._search_key or self._search_key in candidate:
            return 100
        score = fuzz.ratio(self._search_key, candidate)
        return score
