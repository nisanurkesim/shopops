# Policy RAG: split the policy documents into sections, embed them and search them
from dataclasses import dataclass
from pathlib import Path

from config import PROJECT_ROOT

POLICY_DIR = PROJECT_ROOT / "policies"
INDEX_DIR = PROJECT_ROOT / "data" / "chroma"
COLLECTION_NAME = "policies"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"

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
    """Load the embedding model once and reuse it."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    # Normalized vectors: a smaller distance in Chroma means a higher cosine similarity
    vectors = get_model().encode(texts, normalize_embeddings=True)
    return vectors.tolist()


def get_client():
    import chromadb
    return chromadb.PersistentClient(path=str(INDEX_DIR))


def build_index() -> int:
    """Rebuild the policy index from scratch. Returns the number of chunks."""
    chunks = load_chunks()
    client = get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # first build: the collection does not exist yet
    collection = client.create_collection(COLLECTION_NAME)
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