# Check that the ONNX embeddings (src/knowledge/policies.py) match the old
# sentence-transformers embeddings of the same model, before sentence-transformers is removed.
# Compares (1) the vector of every policy section and question, (2) the top-3 search
# results for every question. Writes eval/results/embedding_check.txt.
# Needs sentence-transformers, which is no longer in requirements.txt:
#   pip install sentence-transformers==6.1.0
# Usage: python scripts/compare_embeddings.py
import sys
from pathlib import Path

import numpy as np

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import PROJECT_ROOT
from src.knowledge.policies import EMBEDDING_MODEL, PASSAGE_PREFIX, QUERY_PREFIX, embed, load_chunks

OUT_PATH = PROJECT_ROOT / "eval" / "results" / "embedding_check.txt"

# P1-P7 of the golden set and the queries of tests/test_policies.py
QUESTIONS = [
    "Hasarlı ürün gelirse ne yapmam gerekiyor?",
    "Henüz kargoya verilmemiş bir siparişi nasıl iptal edebilirim?",
    "Siparişin bir kısmını hediye çekiyle ödedim. İade edersem param nasıl geri gelir?",
    "İade süresi hangi günden itibaren sayılıyor?",
    "Siparişim tahmini teslim tarihinden çok sonra geldi. Bu durumda kargo ücretini geri alabilir miyim?",
    "Sipariş bilgilerimi benden başka kimler görebilir?",
    "Siparişime hediye paketi ve not ekletebilir miyim?",
    "hasarlı ürün",
    "siparişimi iptal etmek istiyorum",
    "ürün çok geç geldi, kargo ücretimi geri alabilir miyim",
    "başkasının siparişini görebilir miyim",
    "iade süresi",
]


def old_embed(texts):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL)
    return np.array(model.encode(texts, normalize_embeddings=True))


def top3(query_vector, chunk_vectors, ids):
    scores = chunk_vectors @ query_vector
    best = np.argsort(-scores)[:3]
    return [ids[i] for i in best], scores[best]


def main():
    chunks = load_chunks()
    ids = [c.chunk_id for c in chunks]
    passages = [PASSAGE_PREFIX + c.text_for_embedding() for c in chunks]
    queries = [QUERY_PREFIX + q for q in QUESTIONS]
    texts = passages + queries

    old = old_embed(texts)
    new = np.array(embed(texts))
    cosine = (old * new).sum(axis=1)   # both are length 1

    lines = [
        f"Model: {EMBEDDING_MODEL}",
        f"Texts: {len(passages)} policy sections + {len(queries)} questions",
        f"Cosine similarity old vs new: min {cosine.min():.6f}, mean {cosine.mean():.6f}",
        "",
        "Top-3 search results (old | new):",
    ]
    same_count = 0
    max_score_diff = 0.0
    old_chunks, new_chunks = old[:len(passages)], new[:len(passages)]
    for question, q_old, q_new in zip(QUESTIONS, old[len(passages):], new[len(passages):]):
        ids_old, scores_old = top3(q_old, old_chunks, ids)
        ids_new, scores_new = top3(q_new, new_chunks, ids)
        same = ids_old == ids_new
        same_count += same
        if same:
            max_score_diff = max(max_score_diff, float(np.abs(scores_old - scores_new).max()))
        lines.append(f"  {'SAME' if same else 'DIFFERENT'}  {question}")
        if not same:
            lines.append(f"      old: {ids_old}")
            lines.append(f"      new: {ids_new}")
    lines += [
        "",
        f"Same top-3 for {same_count} of {len(QUESTIONS)} questions; "
        f"largest score difference among them: {max_score_diff:.6f}",
    ]

    text = "\n".join(lines)
    print(text)
    OUT_PATH.write_text(text + "\n", encoding="utf-8")
    print(f"\nWritten to {OUT_PATH}")


if __name__ == "__main__":
    main()
