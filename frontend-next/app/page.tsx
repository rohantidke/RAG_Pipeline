"use client";

import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import clsx from "clsx";
import {
  Bot,
  ChevronDown,
  Copy,
  Database,
  FileText,
  KeyRound,
  LogOut,
  RefreshCw,
  Send,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Upload,
  User,
} from "lucide-react";
import type {
  ChatRequest,
  ChatResponse,
  Citation,
  DocumentListResponse,
  DocumentRecord,
} from "@/lib/chat";

type Role = "assistant" | "user";

type Message = {
  id: string;
  role: Role;
  content: string;
  citations?: Citation[];
  confidence?: number | null;
  abstained?: boolean;
  pending?: boolean;
};

type TokenResponse = {
  accessToken: string;
  tokenType: string;
  expiresAt: string;
};

const TOKEN_STORAGE_KEY = "rag-chat-token";
const TOKEN_EXPIRES_AT_KEY = "rag-chat-token-expires-at";

const prompts = [
  "How does RAG reduce hallucination?",
  "What are embeddings used for in RAG?",
  "How can we evaluate a RAG system?",
];

function createId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function buildFilters(source: string): Record<string, unknown> {
  return source === "all" ? {} : { source };
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  const power = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  const value = bytes / 1024 ** power;
  return `${value >= 10 || power === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[power]}`;
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized === "indexed") {
    return "border-emerald-400/25 bg-emerald-400/10 text-emerald-200";
  }
  if (normalized === "failed") {
    return "border-red-400/25 bg-red-400/10 text-red-200";
  }
  return "border-amber-400/25 bg-amber-400/10 text-amber-100";
}

function getJwtExpiryMs(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) {
      return null;
    }

    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(
      normalizedPayload.padEnd(
        normalizedPayload.length + ((4 - (normalizedPayload.length % 4)) % 4),
        "=",
      ),
    );
    const parsed = JSON.parse(decoded) as { exp?: number };
    return typeof parsed.exp === "number" ? parsed.exp * 1000 : null;
  } catch {
    return null;
  }
}

function isTokenExpired(token: string, expiresAt: string | null): boolean {
  const parsedExpiry = expiresAt ? Date.parse(expiresAt) : Number.NaN;
  if (Number.isFinite(parsedExpiry)) {
    return parsedExpiry <= Date.now();
  }

  const jwtExpiry = getJwtExpiryMs(token);
  return jwtExpiry !== null ? jwtExpiry <= Date.now() : false;
}

function renderInline(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          className="rounded bg-white/[0.08] px-1 py-0.5 text-[0.9em]"
          key={index}
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={index}>{part}</span>;
  });
}

function MarkdownContent({
  content,
  user,
}: {
  content: string;
  user?: boolean;
}) {
  const lines = content.split("\n");
  return (
    <div
      className={clsx(
        "space-y-2 break-words text-[15px] leading-7",
        user ? "text-black" : "text-neutral-100",
      )}
    >
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return <div aria-hidden="true" className="h-1" key={index} />;
        }
        if (trimmed.startsWith("## ")) {
          return (
            <h3 className="pt-1 text-sm font-semibold" key={index}>
              {renderInline(trimmed.slice(3))}
            </h3>
          );
        }
        if (trimmed.startsWith("# ")) {
          return (
            <h3 className="pt-1 text-base font-semibold" key={index}>
              {renderInline(trimmed.slice(2))}
            </h3>
          );
        }
        if (/^[-*]\s+/.test(trimmed)) {
          return (
            <p className="pl-4 before:mr-2 before:content-['-']" key={index}>
              {renderInline(trimmed.slice(2))}
            </p>
          );
        }
        if (/^\d+[.)]\s+/.test(trimmed)) {
          return (
            <p className="pl-4" key={index}>
              {renderInline(trimmed)}
            </p>
          );
        }
        return <p key={index}>{renderInline(trimmed)}</p>;
      })}
    </div>
  );
}

function parseSseChunk(
  chunk: string,
  onToken: (token: string) => void,
  onDone: () => void,
) {
  const events = chunk.split("\n\n");

  for (const event of events) {
    const dataLine = event.split("\n").find((line) => line.startsWith("data:"));

    if (!dataLine) {
      continue;
    }

    const raw = dataLine.slice("data:".length).trim();
    if (!raw) {
      onDone();
      continue;
    }

    try {
      const parsed = JSON.parse(raw) as { token?: string; done?: boolean };
      if (parsed.done) {
        onDone();
      }
      if (parsed.token) {
        onToken(parsed.token);
      }
    } catch {
      onToken(raw);
    }
  }
}

async function responseErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const text = await response.text();
  if (!text.trim()) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(text) as { message?: string; detail?: string };
    return parsed.message || parsed.detail || fallback;
  } catch {
    return text;
  }
}
async function fetchJson<T>(
  url: string,
  payload: ChatRequest,
  accessToken: string | null,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    throw new Error(
      await responseErrorMessage(
        response,
        `Request failed with ${response.status}`,
      ),
    );
  }

  return response.json() as Promise<T>;
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Ask something from the indexed RAG source.",
    },
  ]);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(3);
  const [source, setSource] = useState("all");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState("demo");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("demo123");
  const [authError, setAuthError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registerSuccess, setRegisterSuccess] = useState<string | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [uploadSource, setUploadSource] = useState("");
  const [uploading, setUploading] = useState(false);
  const [refreshingDocs, setRefreshingDocs] = useState(false);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const hasIndexedDocuments = useMemo(
    () =>
      documents.some((document) => document.status.toLowerCase() === "indexed"),
    [documents],
  );
  const hasProcessingDocuments = useMemo(
    () =>
      documents.some(
        (document) => document.status.toLowerCase() === "processing",
      ),
    [documents],
  );
  const canSend =
    input.trim().length > 0 &&
    !streaming &&
    Boolean(token) &&
    hasIndexedDocuments;
  const chatPlaceholder = !token
    ? "Sign in to chat"
    : hasProcessingDocuments && !hasIndexedDocuments
      ? "Document is indexing"
      : hasIndexedDocuments
        ? "Ask anything"
        : "Upload and index a document first";
  const filters = useMemo(() => buildFilters(source), [source]);
  const indexedSources = useMemo(
    () =>
      Array.from(
        new Set(
          documents
            .filter((document) => document.status.toLowerCase() === "indexed")
            .map((document) => document.source),
        ),
      ).sort(),
    [documents],
  );

  useEffect(() => {
    fetch("/api/documents")
      .then((res) => {
        if (res.ok) setToken("authenticated");
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (token) {
      void refreshDocuments(token);
    } else {
      setDocuments([]);
    }
  }, [token]);
  useEffect(() => {
    if (
      !token ||
      !documents.some(
        (document) => document.status.toLowerCase() === "processing",
      )
    ) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void refreshDocuments(token);
    }, 2500);

    return () => window.clearInterval(intervalId);
  }, [documents, token]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  async function hydrateCitations(payload: ChatRequest, assistantId: string) {
    try {
      const finalResponse = await fetchJson<ChatResponse>(
        "/api/chat",
        payload,
        token,
      );
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: finalResponse.answer || message.content,
                citations: finalResponse.citations,
                confidence: finalResponse.confidence,
                abstained: finalResponse.abstained,
                pending: false,
              }
            : message,
        ),
      );
    } catch {
      setMessages((current) =>
        current.map((message) =>
          message.id === assistantId ? { ...message, pending: false } : message,
        ),
      );
    }
  }

  async function refreshDocuments(accessToken = token) {
    if (!accessToken) {
      return;
    }

    try {
      setRefreshingDocs(true);
      setDocumentError(null);
      const response = await fetch("/api/documents");

      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Request failed"));
      }

      const body = (await response.json()) as DocumentListResponse;
      setDocuments(body.documents);
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Could not load documents";
      setDocumentError(message);
    } finally {
      setRefreshingDocs(false);
    }
  }

  async function uploadDocument(file: File | undefined) {
    if (!file || !token) {
      return;
    }

    if (file.size > 50 * 1024 * 1024) {
      setDocumentError("File is too large. Max upload size is 50 MB.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    if (uploadSource.trim()) {
      formData.append("source", uploadSource.trim());
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 45000);

    try {
      setUploading(true);
      setDocumentError(null);
      const response = await fetch("/api/documents/upload", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Request failed"));
      }

      setUploadSource("");
      await refreshDocuments(token);
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Upload failed";
      const finalMessage = controller.signal.aborted
        ? "Upload is taking longer than expected. Use refresh to check status."
        : message;
      setDocumentError(finalMessage);
    } finally {
      window.clearTimeout(timeoutId);
      setUploading(false);
    }
  }

  async function deleteDocument(documentId: string) {
    if (!token) {
      return;
    }

    try {
      setDocumentError(null);
      const response = await fetch(
        `/api/documents/${encodeURIComponent(documentId)}`,
        {
          method: "DELETE",
        },
      );

      if (!response.ok) {
        throw new Error(await responseErrorMessage(response, "Request failed"));
      }

      await refreshDocuments(token);
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Delete failed";
      setDocumentError(message);
    }
  }

  async function submitChat(messageText = input) {
    const question = messageText.trim();
    if (!question || streaming || !token) {
      return;
    }

    if (!hasIndexedDocuments) {
      setError(
        hasProcessingDocuments
          ? "Your document is still indexing. Wait until it becomes indexed, then ask again."
          : "Upload and index a document before asking questions.",
      );
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    const assistantId = createId();
    const payload: ChatRequest = {
      message: question,
      topK,
      filters,
    };

    setError(null);
    setStreaming(true);
    setInput("");
    setMessages((current) => [
      ...current,
      { id: createId(), role: "user", content: question },
      { id: assistantId, role: "assistant", content: "", pending: true },
    ]);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: {
          accept: "text/event-stream",
          "content-type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(await responseErrorMessage(response, "Request failed"));
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const boundary = buffer.lastIndexOf("\n\n");
        if (boundary === -1) {
          continue;
        }

        const ready = buffer.slice(0, boundary + 2);
        buffer = buffer.slice(boundary + 2);

        parseSseChunk(
          ready,
          (token) => {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: `${message.content}${token}` }
                  : message,
              ),
            );
          },
          () => undefined,
        );
      }

      if (buffer.trim()) {
        parseSseChunk(
          buffer,
          (token) => {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: `${message.content}${token}` }
                  : message,
              ),
            );
          },
          () => undefined,
        );
      }

      await hydrateCitations(payload, assistantId);
    } catch (caught) {
      if (controller.signal.aborted) {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? { ...message, pending: false }
              : message,
          ),
        );
        return;
      }

      const message =
        caught instanceof Error ? caught.message : "Chat request failed";
      setError(message);
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? {
                ...item,
                content: message || "The gateway did not return a response.",
                pending: false,
              }
            : item,
        ),
      );
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  async function authenticate(
    nextUsername = username,
    nextPassword = password,
  ) {
    try {
      const response = await fetch("/api/token", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          username: nextUsername,
          password: nextPassword,
        }),
      });

      if (!response.ok) {
        throw new Error("Invalid username or password");
      }

      await response.json();
      setToken("authenticated");
      return true;
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Sign in failed";
      setAuthError(message);
      return false;
    }
  }

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError(null);
    setRegisterError(null);
    setRegisterSuccess(null);
    await authenticate();
  }

  async function registerAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError(null);
    setRegisterError(null);
    setRegisterSuccess(null);

    try {
      const response = await fetch("/api/register", {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({ username, email, password }),
      });

      const text = await response.text();
      if (!response.ok) {
        throw new Error(text || "Registration failed");
      }

      const signedIn = await authenticate(username, password);
      if (signedIn) {
        setRegisterSuccess("Account created and signed in.");
      } else {
        setRegisterSuccess("Account created. Please sign in.");
      }
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Registration failed";
      setRegisterError(message);
    }
  }

  function signOut() {
    stopStreaming();
    setToken(null);
    document.cookie = "rag_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
  }

  function stopStreaming() {
    abortRef.current?.abort();
    setStreaming(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitChat();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitChat();
    }
  }

  function clearChat() {
    setMessages([
      {
        id: "welcome",
        role: "assistant",
        content: "Ask something from the indexed RAG source.",
      },
    ]);
    setError(null);
  }

  return (
    <main className="flex h-screen min-h-screen bg-ink-950 text-neutral-100">
      <aside className="hidden w-[292px] shrink-0 border-r border-white/10 bg-black/70 p-4 lg:flex lg:flex-col">
        <div className="flex h-11 items-center gap-3 px-2">
          <div className="grid size-8 place-items-center rounded-full border border-white/15 bg-white text-black">
            <Sparkles size={17} strokeWidth={2.4} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold">RAG Chat</h1>
            <p className="truncate text-xs text-neutral-500">
              Gateway localhost:8080
            </p>
          </div>
        </div>

        <div className="mt-5 space-y-2">
          <form
            className="mb-4 space-y-2 rounded-lg border border-white/10 bg-white/[0.03] p-3"
            onSubmit={registering ? registerAccount : signIn}
          >
            <div className="flex items-center gap-2 text-xs font-medium text-neutral-400">
              <KeyRound size={14} />
              <span>
                {token
                  ? "Authenticated"
                  : registering
                    ? "Create account"
                    : "Sign in"}
              </span>
            </div>
            {!token && (
              <>
                <input
                  className="h-10 w-full rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Username"
                  value={username}
                />
                {registering && (
                  <input
                    className="h-10 w-full rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="Email"
                    type="email"
                    value={email}
                  />
                )}
                <input
                  className="h-10 w-full rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Password"
                  type="password"
                  value={password}
                />
                {authError && (
                  <p className="text-xs text-red-300">{authError}</p>
                )}
                {registerError && (
                  <p className="text-xs text-red-300">{registerError}</p>
                )}
                {registerSuccess && (
                  <p className="text-xs text-emerald-300">{registerSuccess}</p>
                )}
                <button
                  className="h-10 w-full rounded-md bg-white text-sm font-medium text-black transition hover:bg-neutral-200"
                  type="submit"
                >
                  {registering ? "Create account" : "Sign in"}
                </button>
                <button
                  className="h-9 w-full rounded-md border border-white/10 text-xs text-neutral-400 transition hover:border-white/20 hover:bg-white/[0.06]"
                  onClick={() => {
                    setRegistering((current) => !current);
                    setRegisterError(null);
                    setRegisterSuccess(null);
                    setAuthError(null);
                  }}
                  type="button"
                >
                  {registering
                    ? "Have an account? Sign in"
                    : "Create an account"}
                </button>
              </>
            )}
            {token && (
              <button
                className="h-10 w-full rounded-md border border-white/10 text-sm text-neutral-300 transition hover:border-white/20 hover:bg-white/[0.06]"
                onClick={signOut}
                type="button"
              >
                Sign out
              </button>
            )}
          </form>

          {prompts.map((prompt) => (
            <button
              className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-3 text-left text-sm text-neutral-300 transition hover:border-white/20 hover:bg-white/[0.07]"
              disabled={streaming || !token || !hasIndexedDocuments}
              key={prompt}
              onClick={() => void submitChat(prompt)}
              type="button"
            >
              {prompt}
            </button>
          ))}
        </div>

        <div className="mt-4 space-y-3 rounded-lg border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-medium text-neutral-400">
              <FileText size={14} />
              <span>Documents</span>
            </div>
            <button
              aria-label="Refresh documents"
              className="grid size-7 place-items-center rounded-md text-neutral-500 transition hover:bg-white/[0.06] hover:text-white"
              disabled={!token || uploading || refreshingDocs}
              onClick={() => void refreshDocuments()}
              type="button"
            >
              <RefreshCw
                className={refreshingDocs ? "animate-spin" : ""}
                size={13}
              />
            </button>
          </div>

          <input
            className="h-9 w-full rounded-md border border-white/10 bg-black px-3 text-xs text-neutral-300 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
            disabled={!token || uploading}
            onChange={(event) => setUploadSource(event.target.value)}
            placeholder="Source label"
            value={uploadSource}
          />

          <label
            className={clsx(
              "flex h-10 cursor-pointer items-center justify-center gap-2 rounded-md border border-white/10 text-sm text-neutral-300 transition",
              token && !uploading
                ? "hover:border-white/20 hover:bg-white/[0.06]"
                : "cursor-not-allowed opacity-50",
            )}
          >
            <Upload size={14} />
            <span>{uploading ? "Uploading" : "Upload PDF/TXT/MD"}</span>
            <input
              accept=".pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown"
              className="hidden"
              disabled={!token || uploading}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                void uploadDocument(file);
              }}
              type="file"
            />
          </label>

          {documentError && (
            <p className="text-xs text-red-300">{documentError}</p>
          )}

          <div className="max-h-44 space-y-2 overflow-y-auto pr-1">
            {documents.length === 0 && (
              <p className="rounded-md bg-white/[0.03] px-2.5 py-2 text-xs text-neutral-500">
                No uploaded documents yet.
              </p>
            )}
            {documents.map((document) => (
              <div
                className="rounded-md border border-white/10 bg-black/40 px-2.5 py-2"
                key={document.document_id}
              >
                <div className="flex items-start gap-2">
                  <FileText
                    className="mt-0.5 shrink-0 text-neutral-500"
                    size={13}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-xs font-medium text-neutral-300">
                        {document.filename}
                      </p>
                      <span
                        className={clsx(
                          "shrink-0 rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                          statusTone(document.status),
                        )}
                      >
                        {document.status}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-neutral-600">
                      {document.chunk_count} chunks - {document.page_count ?? 0}{" "}
                      pages - {formatBytes(document.size_bytes)}
                    </p>
                    {document.preview && (
                      <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-neutral-500">
                        {document.preview}
                      </p>
                    )}
                    {document.error_message && (
                      <p className="mt-1 text-[11px] leading-4 text-red-300">
                        {document.error_message}
                      </p>
                    )}
                  </div>
                  <button
                    aria-label={`Delete ${document.filename}`}
                    className="grid size-6 shrink-0 place-items-center rounded text-neutral-600 transition hover:bg-white/[0.08] hover:text-white"
                    onClick={() => void deleteDocument(document.document_id)}
                    type="button"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-auto space-y-3 rounded-lg border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-neutral-400">
            <SlidersHorizontal size={14} />
            <span>Retrieval</span>
          </div>

          <label className="block">
            <span className="mb-2 block text-xs text-neutral-500">
              topK {topK}
            </span>
            <input
              className="h-1.5 w-full accent-white"
              disabled={streaming || !token}
              max={10}
              min={1}
              onChange={(event) => setTopK(Number(event.target.value))}
              type="range"
              value={topK}
            />
          </label>

          <label className="block">
            <span className="mb-2 block text-xs text-neutral-500">source</span>
            <span className="relative block">
              <select
                className="h-10 w-full appearance-none rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition focus:border-white/30"
                disabled={streaming || !token}
                onChange={(event) => setSource(event.target.value)}
                value={source}
              >
                <option value="all">all indexed documents</option>
                {indexedSources.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <ChevronDown
                aria-hidden="true"
                className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-neutral-500"
                size={15}
              />
            </span>
          </label>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/10 bg-black/60 px-4 backdrop-blur md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid size-8 place-items-center rounded-full border border-white/15 bg-white text-black lg:hidden">
              <Sparkles size={16} strokeWidth={2.4} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="truncate text-sm font-semibold">RAG Chat</h2>
                <span
                  className={clsx(
                    "size-2 rounded-full",
                    streaming ? "bg-neutral-300" : "bg-emerald-400",
                  )}
                />
              </div>
              <p className="truncate text-xs text-neutral-500">
                {streaming ? "generating" : "ready"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {token && (
              <button
                aria-label="Sign out"
                className="grid size-9 place-items-center rounded-md border border-white/10 text-neutral-400 transition hover:border-white/20 hover:bg-white/[0.06] hover:text-white"
                onClick={signOut}
                type="button"
              >
                <LogOut size={16} />
              </button>
            )}
            <button
              aria-label="Clear chat"
              className="grid size-9 place-items-center rounded-md border border-white/10 text-neutral-400 transition hover:border-white/20 hover:bg-white/[0.06] hover:text-white"
              onClick={clearChat}
              type="button"
            >
              <Trash2 size={16} />
            </button>
          </div>
        </header>

        <div
          ref={scrollRef}
          className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-6"
        >
          <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
            {!token && (
              <form
                className="mx-auto w-full max-w-sm rounded-xl border border-white/10 bg-ink-900/95 p-4 shadow-glow lg:hidden"
                onSubmit={registering ? registerAccount : signIn}
              >
                <div className="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-200">
                  <KeyRound size={16} />
                  <span>{registering ? "Create account" : "Sign in"}</span>
                </div>
                <div className="space-y-2">
                  <input
                    className="h-11 w-full rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="Username"
                    value={username}
                  />
                  {registering && (
                    <input
                      className="h-11 w-full rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
                      onChange={(event) => setEmail(event.target.value)}
                      placeholder="Email"
                      type="email"
                      value={email}
                    />
                  )}
                  <input
                    className="h-11 w-full rounded-md border border-white/10 bg-black px-3 text-sm text-neutral-200 outline-none transition placeholder:text-neutral-600 focus:border-white/30"
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="Password"
                    type="password"
                    value={password}
                  />
                  {authError && (
                    <p className="text-xs text-red-300">{authError}</p>
                  )}
                  {registerError && (
                    <p className="text-xs text-red-300">{registerError}</p>
                  )}
                  {registerSuccess && (
                    <p className="text-xs text-emerald-300">
                      {registerSuccess}
                    </p>
                  )}
                  <button
                    className="h-11 w-full rounded-md bg-white text-sm font-medium text-black transition hover:bg-neutral-200"
                    type="submit"
                  >
                    {registering ? "Create account" : "Sign in"}
                  </button>
                  <button
                    className="h-10 w-full rounded-md border border-white/10 text-xs text-neutral-400 transition hover:border-white/20 hover:bg-white/[0.06]"
                    onClick={() => {
                      setRegistering((current) => !current);
                      setRegisterError(null);
                      setRegisterSuccess(null);
                      setAuthError(null);
                    }}
                    type="button"
                  >
                    {registering
                      ? "Have an account? Sign in"
                      : "Create an account"}
                  </button>
                </div>
              </form>
            )}

            {messages.map((message) => (
              <article
                className={clsx(
                  "flex gap-3",
                  message.role === "user" ? "justify-end" : "justify-start",
                )}
                key={message.id}
              >
                {message.role === "assistant" && (
                  <div className="mt-1 grid size-8 shrink-0 place-items-center rounded-full border border-white/10 bg-ink-800">
                    <Bot size={16} />
                  </div>
                )}

                <div
                  className={clsx(
                    "min-w-0 max-w-[82%] rounded-xl border px-4 py-3 shadow-glow md:max-w-[72%]",
                    message.role === "user"
                      ? "border-white/12 bg-white text-black"
                      : "border-white/10 bg-ink-900/95 text-neutral-100",
                  )}
                >
                  {message.content ? (
                    <MarkdownContent
                      content={message.content}
                      user={message.role === "user"}
                    />
                  ) : (
                    <div className="whitespace-pre-wrap break-words text-[15px] leading-7">
                      <span className="inline-flex items-center gap-2 text-neutral-500">
                        <RefreshCw className="animate-spin" size={14} />
                        Thinking
                      </span>
                    </div>
                  )}

                  {message.role === "assistant" && message.content && (
                    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/10 pt-3">
                      <button
                        aria-label="Copy answer"
                        className="grid size-8 place-items-center rounded-md text-neutral-500 transition hover:bg-white/[0.06] hover:text-white"
                        onClick={() =>
                          void navigator.clipboard.writeText(message.content)
                        }
                        type="button"
                      >
                        <Copy size={15} />
                      </button>
                      {typeof message.confidence === "number" && (
                        <span className="rounded-md border border-white/10 px-2 py-1 text-xs text-neutral-500">
                          {(message.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                      {message.abstained && (
                        <span className="rounded-md border border-white/10 px-2 py-1 text-xs text-neutral-500">
                          abstained
                        </span>
                      )}
                    </div>
                  )}

                  {message.citations && message.citations.length > 0 && (
                    <div className="mt-3 space-y-2 border-t border-white/10 pt-3">
                      {message.citations.slice(0, 4).map((citation) => (
                        <div
                          className="rounded-md bg-white/[0.04] px-2.5 py-2 text-xs text-neutral-400"
                          key={`${message.id}-${citation.chunkId}`}
                        >
                          <div className="flex items-center gap-2">
                            <Database className="shrink-0" size={13} />
                            <span className="min-w-0 flex-1 truncate text-neutral-300">
                              {citation.filename ||
                                citation.source ||
                                citation.chunkId}
                            </span>
                            {citation.pageNumber !== null &&
                              citation.pageNumber !== undefined && (
                                <span className="shrink-0 text-neutral-500">
                                  p.{citation.pageNumber}
                                </span>
                              )}
                          </div>
                          {citation.textPreview && (
                            <p className="mt-1 line-clamp-2 pl-5 text-[11px] leading-4 text-neutral-500">
                              {citation.textPreview}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {message.role === "user" && (
                  <div className="mt-1 grid size-8 shrink-0 place-items-center rounded-full border border-white/10 bg-white text-black">
                    <User size={16} />
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>

        <footer className="shrink-0 border-t border-white/10 bg-black/75 px-4 py-4 backdrop-blur md:px-6">
          <div className="mx-auto w-full max-w-4xl">
            {error && (
              <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {error}
              </div>
            )}
            {token && !hasIndexedDocuments && (
              <div className="mb-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                {hasProcessingDocuments
                  ? "Your upload is indexing. Chat will unlock when the document status changes to indexed."
                  : "Upload a PDF, TXT, or Markdown document before asking questions."}
              </div>
            )}

            <form
              className="flex items-end gap-2 rounded-xl border border-white/12 bg-ink-900 p-2 shadow-glow focus-within:border-white/25"
              onSubmit={handleSubmit}
            >
              <textarea
                aria-label="Message"
                className="max-h-36 min-h-12 flex-1 bg-transparent px-3 py-3 text-[15px] leading-6 text-neutral-100 outline-none placeholder:text-neutral-600"
                disabled={streaming || !token}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={chatPlaceholder}
                rows={1}
                value={input}
              />

              {streaming ? (
                <button
                  aria-label="Stop"
                  className="grid size-11 shrink-0 place-items-center rounded-lg bg-white text-black transition hover:bg-neutral-200"
                  onClick={stopStreaming}
                  type="button"
                >
                  <Square size={16} fill="currentColor" />
                </button>
              ) : (
                <button
                  aria-label="Send"
                  className="grid size-11 shrink-0 place-items-center rounded-lg bg-white text-black transition hover:bg-neutral-200 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-500"
                  disabled={!canSend}
                  type="submit"
                >
                  <Send size={17} />
                </button>
              )}
            </form>
          </div>
        </footer>
      </section>
    </main>
  );
}
