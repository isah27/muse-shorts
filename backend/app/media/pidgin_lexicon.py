"""Kokoro pronunciation lexicon for Nigerian Pidgin. Kokoro's English G2P reads "dey" as "day", "una" as "you-na",
"sabi" as "sab-eye"; these entries pin the Pidgin pronunciations (IPA in Kokoro's phoneme set)."""
from __future__ import annotations
import re

LEXICON = {
    "dey": "dˈɛ", "wey": "wˈɛ", "don": "dˈɔn", "na": "nˈa", "dem": "dˈɛm", "abi": "ˈabi", "wetin": "wˈɛtin",
    "sabi": "sˈabi", "pikin": "pˈikin", "una": "ˈuna", "oya": "ˈɔja", "di": "di", "e": "ˈɛ", "afta": "ˈafta",
    "wahala": "wahˈala", "comot": "kəmˈɔt", "oga": "ˈɔɡa", "abeg": "abˈɛɡ", "chop": "tʃˈɔp", "waka": "wˈaka",
    "small": "smˈɔl", "plenty": "plˈɛnti", "sef": "sˈɛf", "o": "ˈɔ", "no": "nˈɔ",
}
_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, LEXICON), key=len, reverse=True)) + r")\b", re.I)


def phonemize(text: str, g2p) -> str:
    """g2p(chunk) -> phonemes for plain English chunks; lexicon words are substituted verbatim."""
    out, pos = [], 0
    for m in _RE.finditer(text):
        chunk = text[pos:m.start()]
        if chunk.strip():
            out.append(g2p(chunk).strip())
        out.append(LEXICON[m.group(1).lower()] + (" " if not text[m.end():m.end() + 1] in ".,!?;:" else ""))
        pos = m.end()
    if text[pos:].strip():
        out.append(g2p(text[pos:]).strip())
    s = " ".join(x.strip() if x.strip() not in ".,!?;:" else x.strip() for x in out)
    return re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s+", " ", s)).strip()
