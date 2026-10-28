export type Citation = {
  chunkId: string;
  documentId: string | null;
  filename: string | null;
  pageNumber: number | string | null;
  pageCount: number | string | null;
  source: string | null;
  textPreview: string | null;
  rerankScore: number | null;
};

export type ChatResponse = {
  answer: string;
  abstained: boolean;
  confidence: number | null;
  citations: Citation[];
};

export type ChatRequest = {
  message: string;
  topK: number;
  filters: Record<string, unknown>;
};

export type DocumentRecord = {
  document_id: string;
  user_id?: string | null;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  source: string;
  status: string;
  chunk_count: number;
  created_at: string;
  updated_at?: string | null;
  page_count?: number;
  text_char_count?: number;
  content_hash?: string | null;
  duplicate_of?: string | null;
  preview?: string;
  error_message?: string | null;
};

export type DocumentListResponse = {
  documents: DocumentRecord[];
};
