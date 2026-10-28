import { cookies } from "next/headers";
const gatewayUrl = process.env.SPRING_GATEWAY_URL ?? "http://127.0.0.1:8080";

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get("rag_token")?.value;
  const headers = new Headers({
    accept: "application/json",
    "content-type": "application/json",
  });

  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${gatewayUrl}/api/chat`, {
    method: "POST",
    headers,
    body: await request.text(),
    cache: "no-store",
  });

  return new Response(await response.text(), {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
    },
  });
}
