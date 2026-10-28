import chromadb
import pandas as pd
import json
import numpy as np
from pathlib import Path

def export_chroma_to_csv(chroma_dir="chroma_db", output_csv="text_chunks_and_embeddings_df.csv"):
    print(f"Opening ChromaDB from {chroma_dir}...")
    client = chromadb.PersistentClient(path=chroma_dir)
    col = client.get_collection("rag_chunks")
    total_count = col.count()
    print(f"Total chunks in collection: {total_count}")

    # Fetch in batches of 1000 to be memory efficient
    batch_size = 1000
    all_rows = []
    
    for offset in range(0, total_count, batch_size):
        limit = min(batch_size, total_count - offset)
        print(f"Fetching batch offset {offset} to {offset + limit}...")
        data = col.get(
            limit=limit,
            offset=offset,
            include=["documents", "metadatas", "embeddings"]
        )
        
        ids = data["ids"]
        docs = data["documents"]
        metas = data["metadatas"]
        embeddings = data["embeddings"]
        
        for i in range(len(ids)):
            doc_text = docs[i] if docs is not None else ""
            meta = metas[i] if metas is not None else {}
            emb = embeddings[i] if embeddings is not None else []
            
            # Format embedding as string '[v1, v2, ...]'
            emb_str = "[" + ", ".join(f"{v:.6f}" for v in emb) + "]"
            
            all_rows.append({
                "chunk_id": ids[i],
                "sentence_chunk": doc_text,
                "embedding": emb_str,
                "page_number": meta.get("page_number", 1),
                "chunk_char_count": len(doc_text),
                "chunk_word_count": len(doc_text.split()),
                "chunk_token_count": meta.get("token_count", len(doc_text.split())),
                "source": meta.get("source", meta.get("filename", "document")),
                "document_id": meta.get("document_id", "")
            })
            
    df = pd.DataFrame(all_rows)
    print(f"Writing {len(df)} rows to {output_csv}...")
    df.to_csv(output_csv, index=False)
    print(f"Successfully generated {output_csv} (Size: {Path(output_csv).stat().st_size / (1024*1024):.2f} MB)")

if __name__ == "__main__":
    export_chroma_to_csv()
