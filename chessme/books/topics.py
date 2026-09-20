"""Which topics do the books talk about? Paragraph embeddings, k-means, and each cluster's most characteristic words, to compare with
the hand-written concept list (text.LEXICON). The embedding model (sentence-transformers) is optional: pass any `embed(list[str]) ->
array` to run with something else, or in tests."""
import re
from collections import Counter

import numpy as np

STOP = set("the a an and or of to in on is are was were be been it its as at by for with that this these those from not but so if "
           "then than which who whom will would can could should may might must has have had do does did his her their our your you we he "
           "she they them him i me my one two also more most any each all no there here when where what how why into over after before "
           "black white move moves".split())


def default_embed(model="all-MiniLM-L6-v2"):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(model)
    return lambda texts: m.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)


def kmeans(X, k, iters=30, seed=0):
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), size=min(k, len(X)), replace=False)].copy()
    for _ in range(iters):
        labels = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
        for j in range(len(C)):
            if (labels == j).any():
                C[j] = X[labels == j].mean(0)
    return labels


def top_words(paragraphs, labels, n=8):
    """{cluster: [words]} ranked by how much more often they occur in the cluster than overall (with a small floor)."""
    tok = lambda p: [w for w in re.findall(r"[a-z]{3,}", p.lower()) if w not in STOP]
    overall = Counter(w for p in paragraphs for w in tok(p))
    total = sum(overall.values())
    out = {}
    for c in sorted(set(labels)):
        cnt = Counter(w for p, l in zip(paragraphs, labels) if l == c for w in tok(p))
        size = sum(cnt.values()) or 1
        score = {w: (n_ / size) / ((overall[w] + 5) / total) for w, n_ in cnt.items() if n_ >= 3}
        out[int(c)] = [w for w, _ in sorted(score.items(), key=lambda kv: -kv[1])[:n]]
    return out


def cluster(paragraphs, k=25, embed=None, seed=0):
    """[{"cluster", "size", "words"}] largest first."""
    embed = embed or default_embed()
    labels = kmeans(np.asarray(embed(paragraphs), dtype=float), k, seed=seed)
    words = top_words(paragraphs, labels)
    sizes = Counter(int(l) for l in labels)
    return sorted(({"cluster": c, "size": sizes[c], "words": words[c]} for c in words), key=lambda r: -r["size"])
