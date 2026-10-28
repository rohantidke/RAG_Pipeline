CREATE TABLE app_user (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE documents (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(128),
    size_bytes BIGINT NOT NULL,
    source VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL,
    chunk_count INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    text_char_count INTEGER NOT NULL,
    content_hash VARCHAR(64),
    duplicate_of VARCHAR(64),
    preview TEXT,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT fk_documents_user FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE
);

CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_content_hash ON documents(content_hash);
