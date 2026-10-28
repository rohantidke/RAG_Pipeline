# 📂 Sample Documents for RAG Pipeline

This directory provides curated sample documents that you can immediately upload and index into the RAG Pipeline to test vector retrieval, question answering, and citation generation.

## Included Files

| File | Content Description | Format |
| :--- | :--- | :--- |
| `rag_overview.txt` | In-depth technical guide covering RAG architecture, chunking, embeddings, ChromaDB, and reranking. | Text / Markdown |
| `test_notes.txt` | Short summary note on RAG fundamentals for quick upload testing. | Plain text |
| `test_doc.txt` | Minimal single-line document for rapid ingestion sanity checks. | Plain text |

## Quick Testing Instructions

### Via Next.js Web UI (`http://localhost:3000`)
1. Log in using `demo` / `demo123` (or register a new user).
2. Open the document management sidebar.
3. Drag & drop or browse to select any file in this directory and click **Upload**.
4. Once indexing reaches `indexed`, ask questions in the chat such as:
   - *"What are the six core concepts of RAG?"*
   - *"Why are dense vector embeddings used?"*

### Via cURL / API Gateway
```bash
curl -X POST http://localhost:8080/api/documents/upload \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -F "file=@sample_documents/rag_overview.txt" \
  -F "source=architecture-guide"
```
