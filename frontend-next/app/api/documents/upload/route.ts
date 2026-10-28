import { cookies } from "next/headers";
const gatewayUrl = process.env.SPRING_GATEWAY_URL ?? "http://127.0.0.1:8080";

function jsonError(message: string, status = 502) {
  return Response.json({ message }, { status });
}

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get("rag_token")?.value;
  const headers = new Headers();

  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return jsonError("Upload is too large or invalid multipart data. Max upload size is 50 MB.", 413);
  }

  try {
    const response = await fetch(`${gatewayUrl}/api/documents/upload`, {
      method: "POST",
      headers,
      body: formData,
      cache: "no-store",
    });

    const text = await response.text();
    const contentType = response.headers.get("content-type") ?? "application/json";

    if (!response.ok) {
      let message = response.status === 413
        ? "File is too large. Max upload size is 50 MB."
        : "Upload failed. Make sure FastAPI and Spring Boot are running.";

      if (text.trim()) {
        try {
          const parsed = JSON.parse(text) as { message?: string; detail?: string };
          message = parsed.message || parsed.detail || message;
        } catch {
          message = text;
        }
      }

      return jsonError(message, response.status);
    }

    return new Response(text, {
      status: response.status,
      headers: {
        "content-type": contentType,
      },
    });
  } catch {
    return jsonError("Upload failed. Make sure FastAPI and Spring Boot are running.");
  }
}
