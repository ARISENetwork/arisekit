import path from "node:path";
import { KIT_ROOT } from "@/lib/caseset/paths";
import { createProjectReviewPacket } from "@/lib/caseset/portable-review";
import { buildPortableHtml } from "@/lib/portable-build";
import { newTiming } from "@/lib/answer-table";
import type { PortableProgress } from "@/lib/portable-html";
import type { PortableReview } from "@/lib/portable-review";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  if (process.env.NODE_ENV !== "development") return new Response("Not found", { status: 404 });
  const query = new URL(request.url).searchParams;
  const project = createProjectReviewPacket(path.join(KIT_ROOT, "projects"), "demo", "run2");
  const packet = query.get("scope") === "case" ? project.packets[0] : project;
  let progress: PortableProgress | undefined;
  if (query.get("saved") === "example") {
    const reviewer = "preview-expert";
    const savedAt = "2026-10-23T12:00:00.000Z";
    const reviews = (packet.format === "noharm-project-review-packet-v1" ? packet.packets : [packet]).map((item): PortableReview => {
      const record = structuredClone(item.record);
      record.decisions[1].question = "What testing is needed to evaluate this synthetic case?";
      return { format: "noharm-expert-review-v1", packet: item, reviewer, record, timing: newTiming(new Date(savedAt)), savedAt };
    });
    progress = { review: packet.format === "noharm-project-review-packet-v1" ? { format: "noharm-project-expert-review-v1", packet, reviewer, reviews, savedAt } : reviews[0], caseId: reviews[0].packet.caseId };
  }
  const html = await buildPortableHtml(packet, process.cwd(), progress);
  return new Response(html, {
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}
