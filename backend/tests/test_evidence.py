import json, httpx
from app.agent import evidence as E

PUBMED_XML = """<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<Journal><Title>J Neurosci</Title><JournalIssue><PubDate><Year>2019</Year></PubDate></JournalIssue></Journal>
<ArticleTitle>Action <i>potential</i> review</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Neurons fire spikes.</AbstractText><AbstractText Label="RESULTS">Sodium channels open at threshold.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>456</PMID><Article><ArticleTitle>No abstract</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""

def handler(req: httpx.Request) -> httpx.Response:
    u = str(req.url)
    if "wikipedia.org" in u:
        q = dict(req.url.params)
        if q.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"title": "Neuron"}, {"title": "Neuron (disambiguation)"}]}})
        return httpx.Response(200, json={"query": {"pages": {"1": {"title": "Neuron", "fullurl": "https://en.wikipedia.org/wiki/Neuron",
                              "extract": "A neuron is a nerve cell that fires signals.\n" + "Axons carry signals away from the cell body of the neuron. " * 5}}}})
    if "esearch" in u:
        return httpx.Response(200, json={"esearchresult": {"idlist": ["123", "456"]}})
    if "efetch" in u:
        return httpx.Response(200, text=PUBMED_XML)
    return httpx.Response(404)

def client(): return httpx.Client(transport=httpx.MockTransport(handler))

def test_parse_pubmed_skips_no_abstract_and_labels():
    arts = E.parse_pubmed_xml(PUBMED_XML)
    assert len(arts) == 1 and arts[0]["meta"]["pmid"] == "123"
    assert arts[0]["title"] == "Action potential review"
    assert "Background: Neurons fire spikes." in arts[0]["text"] and arts[0]["url"].endswith("/123/")

def test_web_evidence_ids_and_dedupe(monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    srcs = E.WebEvidence(wiki_n=2, pubmed_n=2, client=client(), cache=False).gather(["neuron firing", "action potential"], topic="action potential in neurons")
    ids = [s.id for s in srcs]
    assert ids == ["W1", "P1"]            # disambiguation page skipped, duplicate pmid/title not repeated
    assert srcs[0].kind == "wikipedia" and srcs[1].meta["pmid"] == "123"
    assert all(s.text for s in srcs)

def test_web_evidence_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    monkeypatch.setattr(E.C, "EVIDENCE_CACHE", tmp_path)
    ev = E.WebEvidence(client=client())
    a = ev.gather(["x"])
    ev.client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))  # network now broken
    assert [s.id for s in ev.gather(["x"])] == [s.id for s in a]

def test_one_source_failing_does_not_kill_the_other(monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    def h(req):
        return httpx.Response(200, text=PUBMED_XML) if "efetch" in str(req.url) else (
            httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}}) if "esearch" in str(req.url) else httpx.Response(404))
    srcs = E.WebEvidence(client=httpx.Client(transport=httpx.MockTransport(h)), cache=False).gather(["q"])
    assert [s.id for s in srcs] == ["P1"]

def test_pick_passages_keeps_intro_and_relevant():
    text = "Intro paragraph about the thing that is long enough to count.\n" + "Irrelevant filler sentence about weather and climate patterns. " * 3 + "\nThe axon myelin sheath speeds conduction of the axon signal quickly.\n"
    out = E.pick_passages(text, "axon myelin", 160)
    assert "Intro paragraph" in out and "myelin" in out


def _off_topic_client():
    xml = PUBMED_XML.replace("Action <i>potential</i> review", "High intensity interval training and oxidative stress").replace(
        "Neurons fire spikes. ", "Athletes trained on a bike.").replace("Sodium channels open at threshold.", "Muscle soreness fell.")
    def h(req):
        u = str(req.url)
        if "esearch" in u: return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        if "efetch" in u: return httpx.Response(200, text=xml)
        return handler(req)
    return httpx.Client(transport=httpx.MockTransport(h))

def test_relevance_filter_drops_off_topic_pubmed_keeps_wikipedia(monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    srcs = E.WebEvidence(client=_off_topic_client(), cache=False).gather(["neuron action potential"], topic="How neurons fire")
    assert [s.id for s in srcs] == ["W1"]

def test_relevance_score_orders_on_topic_above_off_topic():
    terms = E.topic_terms("How the heart pumps blood", ["cardiac cycle"])
    on = E.relevance(terms, "The heart pumps blood", "The heart pumps blood around the body.")[0]
    off = E.relevance(terms, "Cycling and health", "Riding a bike helps fitness.")[0]
    assert on > E.MIN_RELEVANCE > off

def test_llm_judge_overrides_lexical_choice_and_failure_falls_back(monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    def ev(judge): return E.WebEvidence(client=client(), cache=False).gather(["neuron firing"], topic="x", judge=judge)
    assert [s.id for s in ev(lambda t, w, p: ([0], []))] == ["W1"]            # judge drops the PubMed paper
    def boom(t, w, p): raise RuntimeError("llm down")
    assert [s.id for s in ev(boom)][0] == "W1"                                 # falls back, evidence not lost

def test_llm_judge_parses_ids():
    class L:
        def complete_json(self, system, user, schema=""): return {"wikipedia": ["w1", "w0", "junk"], "pubmed": ["p2"]}
    assert E.llm_judge(L())("t", [{"title": "a", "text": "x"}] * 2, [{"title": "b", "text": "y"}] * 3) == ([1, 0], [2])
