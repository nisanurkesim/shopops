# Build the policy RAG index (data/chroma) from the documents in policies/
import sys
from pathlib import Path

# Let this script import config.py and src/ from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src.knowledge.policies import INDEX_DIR, build_index, search_policies


def main():
    n = build_index()
    print(f"Indexed {n} policy sections into {INDEX_DIR}")

    print("\nTest search: 'hasarlı ürün'")
    for hit in search_policies("hasarlı ürün", k=3):
        print(f"  {hit['score']:.3f}  {hit['title']} > {hit['section']}  ({hit['document']})")


if __name__ == "__main__":
    main()