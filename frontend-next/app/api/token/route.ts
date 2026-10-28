const gatewayUrl = process.env.SPRING_GATEWAY_URL ?? "http://127.0.0.1:8080";

export async function POST(request: Request) {
  const response = await fetch(`${gatewayUrl}/api/auth/token`, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: await request.text(),
    cache: "no-store",
  });

  if (!response.ok) {
    return new Response(await response.text(), {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
      },
    });
  }

  const data = await response.json();
  const token = data.access_token || data.accessToken;
  const expires = data.expires_in || 3600;

  return new Response(JSON.stringify({ success: true }), {
    status: 200,
    headers: {
      "content-type": "application/json",
      "Set-Cookie": `rag_token=${token}; HttpOnly; Path=/; Max-Age=${expires}; SameSite=Strict`,
    },
  });
}
