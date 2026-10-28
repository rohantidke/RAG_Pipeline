package com.rag.gateway.document;

import java.io.IOException;
import java.util.List;

import com.rag.gateway.rag.RagServiceException;
import com.rag.gateway.user.UserEntity;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.core.io.ByteArrayResource;

@Service
public class DocumentService {
    private static final Logger log = LoggerFactory.getLogger(DocumentService.class);

    private final DocumentRepository documentRepository;
    private final RestClient ragRestClient;

    public DocumentService(DocumentRepository documentRepository, RestClient ragRestClient) {
        this.documentRepository = documentRepository;
        this.ragRestClient = ragRestClient;
    }

    public DocumentListResponse listDocuments(UserEntity user) {
        syncDocumentsFromRag(user);
        List<DocumentResponse> documents = documentRepository
                .findByUser_IdOrderByCreatedAtDesc(user.getId())
                .stream()
                .map(DocumentResponse::fromEntity)
                .toList();
        return new DocumentListResponse(documents);
    }

    public DocumentResponse getDocument(UserEntity user, String documentId) {
        syncDocumentsFromRag(user);
        DocumentEntity entity = documentRepository
                .findByIdAndUser_Id(documentId, user.getId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Document not found"));
        return DocumentResponse.fromEntity(entity);
    }

    public DocumentUploadResponse uploadDocument(UserEntity user, MultipartFile file, String source) {
        RagDocumentResponse ragResponse = ragUpload(user, file, source);
        DocumentEntity entity = upsertFromRag(user, ragResponse);
        return DocumentUploadResponse.fromEntity(entity, ragResponse.message());
    }

    public DocumentResponse deleteDocument(UserEntity user, String documentId) {
        DocumentEntity entity = documentRepository
                .findByIdAndUser_Id(documentId, user.getId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Document not found"));

        ragDelete(user, documentId);
        documentRepository.delete(entity);
        return DocumentResponse.fromEntity(entity);
    }

    private void syncDocumentsFromRag(UserEntity user) {
        try {
            RagDocumentListResponse response = ragRestClient
                    .get()
                    .uri(uriBuilder -> uriBuilder
                            .path("/documents")
                            .queryParam("user_id", user.getId())
                            .build())
                    .retrieve()
                    .body(RagDocumentListResponse.class);

            if (response == null || response.documents() == null) {
                return;
            }

            for (RagDocumentResponse ragDocument : response.documents()) {
                upsertFromRag(user, ragDocument);
            }
        } catch (RuntimeException exception) {
            log.warn("Could not sync document statuses from RAG service: {}", exception.getMessage());
        }
    }
    private RagDocumentResponse ragUpload(UserEntity user, MultipartFile file, String source) {
        String filename = file.getOriginalFilename() == null ? "document" : file.getOriginalFilename();
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        try {
            body.add("file", new NamedByteArrayResource(file.getBytes(), filename));
        } catch (IOException exc) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Failed to read uploaded file", exc);
        }
        if (source != null && !source.isBlank()) {
            body.add("source", source);
        }
        body.add("user_id", user.getId());

        try {
            return ragRestClient
                    .post()
                    .uri("/documents/upload")
                    .body(body)
                    .retrieve()
                    .body(RagDocumentResponse.class);
        } catch (RestClientResponseException exception) {
            throw new RagServiceException(exception.getStatusCode(), exception.getResponseBodyAsString());
        } catch (ResourceAccessException exception) {
            throw new RagServiceException(HttpStatus.BAD_GATEWAY, "FastAPI RAG service is not reachable at the configured RAG_SERVICE_BASE_URL.");
        }
    }

    private void ragDelete(UserEntity user, String documentId) {
        try {
            ragRestClient
                    .delete()
                    .uri(uriBuilder -> uriBuilder
                            .path("/documents/{documentId}")
                            .queryParam("user_id", user.getId())
                            .build(documentId))
                    .retrieve()
                    .toBodilessEntity();
        } catch (RestClientResponseException exception) {
            throw new RagServiceException(exception.getStatusCode(), exception.getResponseBodyAsString());
        } catch (ResourceAccessException exception) {
            throw new RagServiceException(HttpStatus.BAD_GATEWAY, "FastAPI RAG service is not reachable at the configured RAG_SERVICE_BASE_URL.");
        }
    }

    private DocumentEntity upsertFromRag(UserEntity user, RagDocumentResponse rag) {
        DocumentEntity entity = documentRepository
                .findByIdAndUser_Id(rag.documentId(), user.getId())
                .orElseGet(DocumentEntity::new);

        entity.setId(rag.documentId());
        entity.setUser(user);
        entity.setFilename(rag.filename());
        entity.setContentType(rag.contentType());
        entity.setSizeBytes(rag.sizeBytes());
        entity.setSource(rag.source());
        entity.setStatus(rag.status());
        entity.setChunkCount(rag.chunkCount());
        entity.setPageCount(rag.pageCount());
        entity.setTextCharCount(rag.textCharCount());
        entity.setContentHash(rag.contentHash());
        entity.setDuplicateOf(rag.duplicateOf());
        entity.setPreview(rag.preview());
        entity.setErrorMessage(rag.errorMessage());

        return documentRepository.save(entity);
    }

    private static class NamedByteArrayResource extends ByteArrayResource {
        private final String filename;

        NamedByteArrayResource(byte[] byteArray, String filename) {
            super(byteArray);
            this.filename = filename == null || filename.isBlank() ? "document" : filename;
        }

        @Override
        public String getFilename() {
            return filename;
        }
    }
}
