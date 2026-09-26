// Container healthcheck: proves the Next.js server is up without calling the API.
export const dynamic = "force-dynamic";

export function GET() {
  return new Response("ok", { headers: { "content-type": "text/plain" } });
}
