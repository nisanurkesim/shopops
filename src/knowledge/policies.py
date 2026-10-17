# Policy RAG: split the policy documents into sections, embed them and search them
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import PROJECT_ROOT

POLICY_DIR = PROJECT_ROOT / "policies"
INDEX_DIR = PROJECT_ROOT / "data" / "chroma"
COLLECTION_NAME = "policies"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"

# The model runs from its ONNX export with onnxruntime, not with sentence-transformers:
# sentence-transformers needs torch, which is too large for the free demo server.
# Same model and weights; scripts/compare_embeddings.py measured that the vectors match.
# Pinned to the commit that added the ONNX files, so the index and the queries always
# use the same files.
MODEL_REVISION = "ffdcc22a9a5c973ef0470385cef91e1ecb461d9f"
MODEL_FILE = "onnx/model.onnx"
TOKENIZER_FILE = "onnx/tokenizer.json"
MAX_TOKENS = 512   # the model's input limit; longer texts are cut, as in sentence-transformers

# The e5 models expect these prefixes on every input
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


@dataclass
class Chunk:
    chunk_id: str    # e.g. "return_policy#2"
    document: str    # file name, e.g. "return_policy.md"
    title: str       # document title (the "# " line), shown to the customer
    section: str     # section title (a "## " line), shown to the customer
    body: str        # section text

    def text_for_embedding(self) -> str:
        # Title and section name help the search, so they are part of the text
        return f"{self.title} - {self.section}\n{self.body}"


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def split_document(path: Path) -> list[Chunk]:
    """Split one markdown file into one chunk per '## ' section."""
    title = path.stem
    chunks = []
    section = None
    lines = []

    def close_section():
        body = "\n".join(lines).strip()
        if section is not None and body:
            chunk_id = f"{path.stem}#{len(chunks)}"
            chunks.append(Chunk(chunk_id, path.name, title, section, body))

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            close_section()
            section = line[3:].strip()
            lines = []
        elif section is not None:
            lines.append(line)
    close_section()
    return chunks


def load_chunks(policy_dir: Path = POLICY_DIR) -> list[Chunk]:
    """All chunks from every policy document. README.md is not a policy."""
    chunks = []
    for path in sorted(policy_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        chunks.extend(split_document(path))
    return chunks


# ---------------------------------------------------------------------------
# Embedding and index
# ---------------------------------------------------------------------------

_model = None


def get_model():
    """Load the tokenizer and the ONNX model once and reuse them.
    The first call downloads the files from Hugging Face (about 490 MB) into its cache."""
    global _model
    if _model is None:
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(
            hf_hub_download(EMBEDDING_MODEL, TOKENIZER_FILE, revision=MODEL_REVISION))
        tokenizer.enable_truncation(max_length=MAX_TOKENS)
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        session = onnxruntime.InferenceSession(
            hf_hub_download(EMBEDDING_MODEL, MODEL_FILE, revision=MODEL_REVISION),
            providers=["CPUExecutionProvider"])
        _model = (tokenizer, session)
    return _model


def mean_pool(token_vectors: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """One vector per text: the mean of its token vectors, padding left out, scaled to
    length 1. These are the steps sentence-transformers runs for the e5 models."""
    mask = attention_mask[:, :, None].astype(np.float32)
    vectors = (token_vectors * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
    return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)


def embed(texts: list[str]) -> list[list[float]]:
    # Normalized vectors: a smaller distance in Chroma means a higher cosine similarity
    tokenizer, session = get_model()
    encodings = tokenizer.encode_batch(texts)
    inputs = {
        "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
        "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
    }
    wanted = {i.name for i in session.get_inputs()}
    token_vectors = session.run(None, {k: v for k, v in inputs.items() if k in wanted})[0]
    return mean_pool(token_vectors, inputs["attention_mask"]).tolist()


def get_client():
    import chromadb
    return chromadb.PersistentClient(path=str(INDEX_DIR))


def build_index() -> int:
    """Rebuild the policy index from scratch. Returns the number of chunks.

    The whole folder is removed first: delete_collection can leave the old vector files
    behind (seen on Windows), and the folder is committed, so it must hold only this index.
    """
    chunks = load_chunks()
    if INDEX_DIR.exists():
        shutil.rmtree(INDEX_DIR)
    collection = get_client().create_collection(COLLECTION_NAME)
    collection.add(
        ids=[c.chunk_id for c in chunks],
        embeddings=embed([PASSAGE_PREFIX + c.text_for_embedding() for c in chunks]),
        documents=[c.body for c in chunks],
        metadatas=[{"document": c.document, "title": c.title, "section": c.section} for c in chunks],
    )
    return len(chunks)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_policies(query: str, k: int = 3) -> list[dict]:
    """Return the k policy sections closest to the query, best first."""
    collection = get_client().get_collection(COLLECTION_NAME)
    result = collection.query(query_embeddings=embed([QUERY_PREFIX + query]), n_results=k)
    hits = []
    for chunk_id, body, meta, distance in zip(
        result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append({
            "chunk_id": chunk_id,
            "document": meta["document"],
            "title": meta["title"],
            "section": meta["section"],
            "text": body,
            # Chroma's default distance is squared L2; for normalized vectors
            # it equals 2 - 2 * cosine, so this gives back the cosine similarity
            "score": round(1 - distance / 2, 3),
        })
    return hits