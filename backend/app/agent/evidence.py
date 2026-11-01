"""Evidence retrieval: Wikipedia (MediaWiki API) + PubMed (NCBI E-utilities). Both are free and keyless.

Every source gets a short id (W1.., P1..) that the writer must cite and the claim critic checks against.
Source text is capped so each claim check stays cheap. Results are cached on disk by query.
"""
from __future__ import annotations
import hashlib, json, re, time, xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
import httpx
from .. import config as C

UA = f"MuseShorts/0.1 (hackathon project; {C.CONTACT_EMAIL})"
WIKI_API = "https://en.wikipedia.org/w/api.php"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
WIKI_CHARS, PUBMED_CHARS = 4500, 2200

@dataclass
class Source:
    id: str
    kind: str          # "wikipedia" | "pubmed" | "mock"
    title: str
    url: str
    text: str
    meta: dict | None = None
    def public(self) -> dict:
        d = asdict(self); d["text"] = self.text; return d

def _get(url: str, params: dict, client: httpx.Client | None = None, tries: int = 3) -> httpx.Response:
    c = client or httpx
    err: Exception | None = None
    for i in range(tries):
        try:
            r = c.get(url, params=params, headers={"User-Agent": UA}, timeout=25)
            if r.status_code in (429, 500, 502, 503):
                time.sleep(1.5 * (i + 1)); continue
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"evidence request failed: {url.split('/')[2]} (HTTP {e.response.status_code})") from None
        except httpx.TransportError as e:
            err = e; time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"evidence request failed: {url.split('/')[2]} ({type(err).__name__ if err else 'status'})")

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.\-]", " ", s.lower())).strip()

def pick_passages(text: str, query: str, limit: int) -> str:
    """Keep the intro plus the paragraphs that overlap most with the query, in original order, up to `limit` chars."""
    paras = [p.strip() for p in re.split(r"\n{1,}", text) if len(p.strip()) > 40 and not p.strip().startswith("==")]
    if not paras:
        return text[:limit]
    qw = set(_norm(query).split())
    scored = sorted(range(len(paras)), key=lambda i: (i != 0, -len(qw & set(_norm(paras[i]).split()))))
    keep, used = [], 0
    for i in scored:
        if used + len(paras[i]) > limit and keep:
            continue
        keep.append(i); used += len(paras[i])
        if used >= limit:
            break
    return "\n".join(paras[i] for i in sorted(keep))[:limit + 400]

def wikipedia(query: str, n: int = 2, client: httpx.Client | None = None) -> list[dict]:
    s = _get(WIKI_API, {"action": "query", "list": "search", "srsearch": query, "srlimit": n + 2, "format": "json", "srprop": ""}, client).json()
    titles = [h["title"] for h in s.get("query", {}).get("search", [])
              if "disambiguation" not in h["title"].lower()][:n]
    out = []
    for t in titles:
        d = _get(WIKI_API, {"action": "query", "prop": "extracts|info", "explaintext": 1, "exsectionformat": "plain", "inprop": "url",
                            "titles": t, "redirects": 1, "format": "json"}, client).json()
        for page in d.get("query", {}).get("pages", {}).values():
            txt = page.get("extract") or ""
            if len(txt) > 200:
                out.append({"title": page["title"], "url": page.get("fullurl") or f"https://en.wikipedia.org/wiki/{page['title'].replace(' ', '_')}",
                            "text": pick_passages(txt, query, WIKI_CHARS)})
    return out

def pubmed(query: str, n: int = 2, client: httpx.Client | None = None) -> list[dict]:
    common = {"tool": "muse-shorts", "email": C.CONTACT_EMAIL}
    ids = _get(f"{EUTILS}/esearch.fcgi", {**common, "db": "pubmed", "retmode": "json", "retmax": n, "sort": "relevance",
                                           "term": f"({query}) AND hasabstract[text] AND (review[pt] OR systematic[sb] OR textbooks[pt])"}, client
               ).json().get("esearchresult", {}).get("idlist", [])
    if not ids:  # relax the publication-type filter
        ids = _get(f"{EUTILS}/esearch.fcgi", {**common, "db": "pubmed", "retmode": "json", "retmax": n, "sort": "relevance",
                                               "term": f"({query}) AND hasabstract[text]"}, client).json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    return parse_pubmed_xml(_get(f"{EUTILS}/efetch.fcgi", {**common, "db": "pubmed", "retmode": "xml", "id": ",".join(ids)}, client).text)

def parse_pubmed_xml(xml_text: str) -> list[dict]:
    out = []
    for art in ET.fromstring(xml_text).findall(".//PubmedArticle"):
        pmid = (art.findtext(".//PMID") or "").strip()
        title = "".join(art.find(".//ArticleTitle").itertext()).strip() if art.find(".//ArticleTitle") is not None else ""
        parts = []
        for a in art.findall(".//Abstract/AbstractText"):
            label, txt = a.get("Label"), "".join(a.itertext()).strip()
            if txt:
                parts.append(f"{label.title()}: {txt}" if label and label.upper() not in ("UNLABELLED", "UNASSIGNED") else txt)
        if not (pmid and parts):
            continue
        out.append({"title": title, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "text": "\n".join(parts)[:PUBMED_CHARS],
                    "meta": {"pmid": pmid, "journal": (art.findtext(".//Journal/Title") or "").strip(),
                             "year": (art.findtext(".//JournalIssue/PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or "").strip()[:4]}})
    return out

GENERIC = {"human", "humans", "body", "physiology", "physiological", "anatomy", "anatomical", "mechanism", "mechanisms", "function", "functions",
           "process", "processes", "system", "basic", "overview", "review", "work", "works", "does", "what", "how", "why", "explained", "role", "the", "and", "for", "with", "from", "that", "this", "are", "into", "its"}

def _stems(text: str) -> set[str]:
    return {w[:4] if len(w) >= 5 else w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 3 and w not in GENERIC}

def topic_terms(topic: str | None, queries: list[str]) -> tuple[set[str], set[str]]:
    """(all terms, core terms): core = words of the topic itself, which a relevant source must actually be about."""
    core = _stems(topic or "")
    return core | _stems(" ".join(queries)), core or _stems(" ".join(queries[:1]))

def relevance(terms: tuple[set[str], set[str]] | set[str], title: str, text: str) -> tuple[float, int]:
    """(score 0..1, core title hits). A title that names a core topic word counts most, then core coverage of the abstract, then coverage
    of all query terms. Used to drop off-topic PubMed hits (a HIIT paper for a heart-pumping query) and to rank Wikipedia candidates."""
    allt, core = terms if isinstance(terms, tuple) else (terms, terms)
    if not allt:
        return 1.0, 1
    t, both = _stems(title), _stems(title + " " + text)
    th = len(core & t)
    return (0.4 * min(1.0, th / max(1, min(2, len(core))))
            + 0.3 * len(core & both) / max(1, len(core))
            + 0.3 * len(allt & both) / len(allt)), th

MIN_RELEVANCE = 0.6

class WebEvidence:
    name = "Wikipedia + PubMed"
    def __init__(self, wiki_n: int = 3, pubmed_n: int = 2, client: httpx.Client | None = None, cache: bool = True):
        self.wiki_n, self.pubmed_n, self.client, self.cache = wiki_n, pubmed_n, client, cache

    def gather(self, queries: list[str], topic: str | None = None, judge=None) -> list[Source]:
        """judge(topic, wiki_candidates, pubmed_candidates) -> (wiki_idx, pubmed_idx) lists, best first: an LLM relevance filter.
        Without it (or if it fails) a lexical score is used."""
        key = hashlib.sha1(json.dumps([queries, topic, self.wiki_n, self.pubmed_n, "v3", bool(judge)]).encode()).hexdigest()[:16]
        cf = C.EVIDENCE_CACHE / f"{key}.json"
        if self.cache and cf.exists():
            return [Source(**d) for d in json.loads(cf.read_text())]
        terms = topic_terms(topic, queries)
        wiki: list[dict] = []
        pm: list[dict] = []
        seen_t, seen_p = set(), set()
        for q in queries[:3]:
            try:
                for w in wikipedia(q, self.wiki_n + 1, self.client):
                    if w["title"] not in seen_t:
                        seen_t.add(w["title"]); wiki.append(w)
            except RuntimeError:
                pass
            try:   # a wide pool, then rank by relevance: PubMed's own ranking often puts loosely related papers first
                for p in pubmed(q, 6, self.client):
                    if p["meta"]["pmid"] not in seen_p:
                        seen_p.add(p["meta"]["pmid"]); pm.append(p)
            except (RuntimeError, ET.ParseError):
                pass
            time.sleep(0.35)  # stay under NCBI's 3 req/s keyless limit
        # Wikipedia first (plain-language overview, gets ids W1..). Lexical pre-rank shortlists, then the judge (or a threshold) decides.
        rank = lambda items: [x for _, x in sorted(enumerate(items), key=lambda t: (-relevance(terms, t[1]["title"], t[1]["text"])[0], t[0]))]
        wiki, pm_all = rank(wiki), rank(pm)
        keep = None
        if judge and (wiki or pm_all):
            try:
                wi, pi = judge(topic or queries[0], wiki[:6], pm_all[:8])
                keep = ([wiki[:6][i] for i in wi if 0 <= i < len(wiki[:6])][:self.wiki_n], [pm_all[:8][i] for i in pi if 0 <= i < len(pm_all[:8])][:self.pubmed_n])
            except Exception:  # noqa: BLE001 — a judge failure must not lose the evidence step
                keep = None
        if keep is None:
            keep = (wiki[:self.wiki_n],
                    [p for p in pm_all if (lambda r: r[0] >= MIN_RELEVANCE and r[1] >= 1)(relevance(terms, p["title"], p["text"]))][:self.pubmed_n])
        wiki, pm = keep
        srcs = [Source(f"W{i + 1}", "wikipedia", w["title"], w["url"], w["text"]) for i, w in enumerate(wiki)]
        srcs += [Source(f"P{i + 1}", "pubmed", p["title"], p["url"], p["text"], p["meta"]) for i, p in enumerate(pm)]
        if self.cache and srcs:
            C.EVIDENCE_CACHE.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps([asdict(s) for s in srcs]))
        return srcs

def _expand(self, existing: list[Source], queries: list[str], topic: str | None = None, judge=None, extra: int = 2) -> list[Source]:
    """Fetch MORE sources (wider search, new queries) for a topic whose evidence is too thin. Returns only sources not already held,
    numbered after the existing ids (W4, P3, ...) so earlier citations stay valid."""
    nw = sum(1 for s in existing if s.kind == "wikipedia"); npm = sum(1 for s in existing if s.kind == "pubmed")
    wide = WebEvidence(wiki_n=nw + extra, pubmed_n=npm + extra, client=self.client, cache=self.cache)
    have = {s.url for s in existing}
    new = [s for s in wide.gather(queries, topic=topic, judge=judge) if s.url not in have]
    out = []
    for s in new:
        if s.kind == "wikipedia": nw += 1; sid = f"W{nw}"
        else: npm += 1; sid = f"P{npm}"
        out.append(Source(sid, s.kind, s.title, s.url, s.text, s.meta))
    return out
WebEvidence.expand = _expand

# Offline fixture so the mock pipeline (no keys, no network) still demonstrates the evidence + claim gate.
MOCK_NEURON = (
    "A neuron, also known as a nerve cell, is an excitable cell that fires electric signals called action potentials across a neural network. "
    "Neurons have three main parts: dendrites that receive signals, a cell body that integrates them, and an axon that carries the signal away. "
    "At rest, the membrane potential of a typical neuron is about minus seventy millivolts. "
    "When the membrane depolarises past a threshold, voltage-gated sodium channels open and sodium ions rush in, and the voltage spikes. "
    "The action potential then travels down the axon. In myelinated axons the signal jumps between gaps in the myelin sheath called nodes of Ranvier, which speeds conduction. "
    "Myelinated axons can conduct impulses at up to about one hundred and twenty metres per second. "
    "At the synapse the signal triggers the release of neurotransmitters that cross a small gap to the next cell. "
    "The human brain contains roughly eighty six billion neurons.")

class MockEvidence:
    name = "Offline fixture"
    def gather(self, queries: list[str], topic: str | None = None, judge=None) -> list[Source]:
        q = " ".join(queries)
        return [Source("W1", "mock", "Neuron (fixture)", "https://en.wikipedia.org/wiki/Neuron", MOCK_NEURON if "neuron" in q.lower() else
                       f"{queries[0]} is a topic in human biology. It is described in anatomy and physiology textbooks. Its structure and function depend on cells working together in a coordinated way."),
                Source("P1", "mock", "Action potential conduction (fixture)", "https://pubmed.ncbi.nlm.nih.gov/0/",
                       "Action potentials are all-or-none events. Conduction velocity in myelinated fibres is higher than in unmyelinated fibres, reaching about one hundred and twenty metres per second in the fastest fibres.",
                       {"pmid": "0"})]

MockEvidence.expand = lambda self, existing, queries, topic=None, judge=None, extra=2: []   # the fixture has nothing more to fetch

def get_evidence():
    return WebEvidence() if C.EVIDENCE_PROVIDER == "web" else MockEvidence()


def llm_judge(llm):
    """Build a judge from an LLM: keep only sources that genuinely help explain the topic in a 45-75 s explainer."""
    from . import prompts as P
    def judge(topic, wiki, pm):
        brief = lambda xs, k: [{"id": f"{k}{i}", "title": x["title"], "text": x["text"][:300]} for i, x in enumerate(xs)]
        out = llm.complete_json(P.RELEVANCE, json.dumps({"topic": topic, "wikipedia": brief(wiki, "w"), "pubmed": brief(pm, "p")}), P.RELEVANCE_SCHEMA)
        idx = lambda ids, k: [int(i[len(k):]) for i in ids if isinstance(i, str) and i.startswith(k) and i[len(k):].isdigit()]
        return idx(out.get("wikipedia", []), "w"), idx(out.get("pubmed", []), "p")
    return judge
