package com.rag.gateway.document;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

public interface DocumentRepository extends JpaRepository<DocumentEntity, String> {
    List<DocumentEntity> findByUser_IdOrderByCreatedAtDesc(String userId);

    Optional<DocumentEntity> findByIdAndUser_Id(String documentId, String userId);

    void deleteByIdAndUser_Id(String documentId, String userId);
}
