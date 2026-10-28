const gatewayUrl = process.env.SPRING_GATEWAY_URL ?? "http://127.0.0.1:8080";

export async function POST(request: Request) {
  const response = await fetch(`${gatewayUrl}/api/auth/register`, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: await request.text(),
    cache: "no-store",
  });

  return new Response(await response.text(), {
    status: response.status,
    headers: {
      "content-type":
        response.headers.get("content-type") ?? "application/json",
    },
  });
}
