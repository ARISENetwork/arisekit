import { projectVersion } from "@/lib/arisekit-version";

export function GET() {
  return Response.json({ service: "arisekit-noharm", version: projectVersion() }, { headers: { "Cache-Control": "no-store" } });
}
