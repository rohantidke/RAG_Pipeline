package com.rag.gateway.document;

import com.rag.gateway.user.UserEntity;
import com.rag.gateway.user.UserService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/documents")
public class DocumentController {
    private final DocumentService documentService;
    private final UserService userService;

    public DocumentController(DocumentService documentService, UserService userService) {
        this.documentService = documentService;
        this.userService = userService;
    }

    @GetMapping
    public ResponseEntity<DocumentListResponse> listDocuments(@AuthenticationPrincipal Jwt jwt) {
        UserEntity user = userService.requireByUsername(jwt.getSubject());
        return ResponseEntity.ok(documentService.listDocuments(user));
    }

    @GetMapping("/{documentId}")
    public ResponseEntity<DocumentResponse> getDocument(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable String documentId
    ) {
        UserEntity user = userService.requireByUsername(jwt.getSubject());
        return ResponseEntity.ok(documentService.getDocument(user, documentId));
    }

    @PostMapping(path = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<DocumentUploadResponse> uploadDocument(
            @AuthenticationPrincipal Jwt jwt,
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "source", required = false) String source
    ) {
        UserEntity user = userService.requireByUsername(jwt.getSubject());
        return ResponseEntity.ok(documentService.uploadDocument(user, file, source));
    }

    @DeleteMapping("/{documentId}")
    public ResponseEntity<DocumentResponse> deleteDocument(
            @AuthenticationPrincipal Jwt jwt,
            @PathVariable String documentId
    ) {
        UserEntity user = userService.requireByUsername(jwt.getSubject());
        return ResponseEntity.ok(documentService.deleteDocument(user, documentId));
    }
}
