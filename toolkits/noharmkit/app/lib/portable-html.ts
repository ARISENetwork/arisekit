import { parsePortableReview, parseProjectReview, type PortableProjectReview, type PortableReview, type ProjectReviewPacket, type ReviewPacket } from "./portable-review";

export interface PortableShell {
  js: string;
  css: string;
  version: string;
}

export interface PortableProgress {
  review: PortableReview | PortableProjectReview;
  caseId: string;
}

export function parsePortableProgress(value: unknown, assignment?: ReviewPacket | ProjectReviewPacket): PortableProgress {
  const progress = value as PortableProgress | null;
  const review = progress?.review?.format === "noharm-project-expert-review-v1"
    ? parseProjectReview(progress.review) : parsePortableReview(progress?.review);
  if (assignment && JSON.stringify(review.packet) !== JSON.stringify(assignment)) throw new Error("The saved review belongs to a different assignment.");
  const packets = review.packet.format === "noharm-project-review-packet-v1" ? review.packet.packets : [review.packet];
  if (!packets.some((packet) => packet.caseId === progress?.caseId)) throw new Error("The saved review's current case is not in its assignment.");
  return { review, caseId: progress!.caseId };
}

export function parsePortableReviewFile(text: string): PortableReview | PortableProjectReview {
  if (!text.trimStart().startsWith("<")) {
    const value: unknown = JSON.parse(text);
    return (value as PortableProjectReview | null)?.format === "noharm-project-expert-review-v1" ? parseProjectReview(value) : parsePortableReview(value);
  }
  const dataScripts = [...text.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)]
    .filter((match) => /(?:^|\s)id=["']review-progress["'](?:\s|$)/i.test(match[1]) && /(?:^|\s)type=["']application\/json["'](?:\s|$)/i.test(match[1]));
  if (dataScripts.length > 1) throw new Error("This HTML contains multiple saved reviews. Choose an unmodified downloaded review file.");
  const data = dataScripts[0]?.[2];
  if (!data) throw new Error("This HTML has no saved review. Choose the HTML downloaded by the expert after saving their work.");
  return parsePortableProgress(JSON.parse(data)).review;
}

export function renderPortableHtml(packet: ReviewPacket | ProjectReviewPacket, shell: PortableShell, progress?: PortableProgress): string {
  if (progress) parsePortableProgress(progress, packet);
  const json = (value: unknown): string => JSON.stringify(value).replace(/</g, "\\u003c");
  const csp = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  const saved = progress ? `<script id="review-progress" type="application/json">${json(progress)}</script>` : "";
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>Expert Rubric Review</title><style id="portable-styles">${shell.css.replace(/<\/style/gi, "<\\/style")}</style></head><body><div id="portable-editor"></div><div class="portable-version">${shell.version}</div><noscript>Open this file in a browser with JavaScript enabled to review the rubric.</noscript><script id="review-packet" type="application/json">${json(packet)}</script>${saved}<script id="portable-runtime">${shell.js.replace(/<\/script/gi, "<\\/script")}</script></body></html>`;
}
