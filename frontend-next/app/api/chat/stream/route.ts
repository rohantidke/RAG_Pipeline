import { cookies } from "next/headers";
const gatewayUrl = process.env.SPRING_GATEWAY_URL ?? "http://127.0.0.1:8080";

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get("rag_token")?.value;
  const headers = new Headers({
    accept: "text/event-stream",
    "content-type": "application/json",
  });

  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${gatewayUrl}/api/chat/stream`, {
    method: "POST",
    headers,
    body: await request.text(),
    cache: "no-store",
  });

  if (!response.body) {
    return new Response("No stream returned by gateway", { status: 502 });
  }

  return new Response(response.body, {
    status: response.status,
    headers: {
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "content-type": "text/event-stream; charset=utf-8",
    },
  });
}
