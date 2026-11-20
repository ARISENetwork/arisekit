import { projectsRoot } from "@/lib/caseset/paths";
import { NextRequest, NextResponse } from "next/server";
import { projectFailureStatus } from "@/lib/project-files";
import { requestOrigin } from "@/lib/request-origin";
import { deletePrompt, loadPrompts, recordedPromptHashes, savePrompt, usedPromptIds } from "@/lib/response-prompts";

function failure(caught: unknown): NextResponse {
  const error = caught as Error;
  return NextResponse.json({ error: error.message }, { status: projectFailureStatus(caught, caught instanceof TypeError || caught instanceof SyntaxError ? 400 : 500) });
}

function foreign(request: NextRequest): NextResponse | null {
  const origin = request.headers.get("origin");
  return origin && origin !== new URL(requestOrigin(request)).origin ? NextResponse.json({ error: "Prompt changes must come from this site." }, { status: 403 }) : null;
}

function projectParam(request: NextRequest): string {
  const project = request.nextUrl.searchParams.get("project");
  if (!project) throw new TypeError("Choose a project.");
  return project;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const project = projectParam(request);
    const root = projectsRoot();
    return NextResponse.json({ prompts: loadPrompts(root, project), used: [...usedPromptIds(root, project)], recorded: recordedPromptHashes(root, project) });
  } catch (caught) { return failure(caught); }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  const rejected = foreign(request);
  if (rejected) return rejected;
  try {
    const body = await request.json();
    if (typeof body.project !== "string") throw new TypeError("Choose a project.");
    if (typeof body.name !== "string" || typeof body.text !== "string") throw new TypeError("Provide a prompt name and text.");
    if (body.replaces !== undefined && typeof body.replaces !== "string") throw new TypeError("Replaces must be a prompt id.");
    const root = projectsRoot();
    const prompt = savePrompt(root, body.project, { name: body.name, text: body.text, replaces: body.replaces });

    return NextResponse.json({ prompt }, { status: 201 });
  } catch (caught) { return failure(caught); }
}

export async function DELETE(request: NextRequest): Promise<NextResponse> {
  const rejected = foreign(request);
  if (rejected) return rejected;
  try {
    const project = projectParam(request);
    const id = request.nextUrl.searchParams.get("id");
    if (!id) throw new TypeError("Choose a prompt.");
    const root = projectsRoot();
    deletePrompt(root, project, id);

    return NextResponse.json({ deleted: id });
  } catch (caught) { return failure(caught); }
}
