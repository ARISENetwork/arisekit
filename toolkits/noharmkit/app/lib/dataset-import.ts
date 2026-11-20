export interface DatasetCase {
  source_item_id?: string;
  id?: string;
  task: string;
  solutions: string[];
  errors: string;
}

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i++; }
      else if (quoted || !field) quoted = !quoted;
      else throw new Error("Unexpected quote in CSV field.");
    } else if (!quoted && char === ",") { row.push(field); field = ""; }
    else if (!quoted && (char === "\n" || char === "\r")) {
      row.push(field); if (row.some((value) => value.trim())) rows.push(row);
      row = []; field = ""; if (char === "\r" && text[i + 1] === "\n") i++;
    } else field += char;
  }
  if (quoted) throw new Error("CSV contains an unclosed quoted field.");
  row.push(field); if (row.some((value) => value.trim())) rows.push(row);
  return rows;
}

function caseRecord(value: unknown, index: number): DatasetCase {
  const fail = (message: string): never => { throw new Error(`Case ${index + 1}: ${message}`); };
  if (!value || typeof value !== "object" || Array.isArray(value)) return fail("expected an object.");
  const entries = Object.entries(value).map(([key, content]) => [key.trim().toLowerCase(), content] as const);
  const record = Object.fromEntries(entries) as Record<string, unknown>;
  const get = (keys: string[]): unknown => {
    const found = keys.filter((key) => record[key] !== undefined);
    if (found.length > 1) return fail(`multiple columns match ${keys[0]}. Use one field name.`);
    return record[found[0]];
  };
  const task = get(["task", "input", "presentation"]);
  const solution = get(["solutions", "solution", "reference", "recommendations"]);
  if (typeof task !== "string" || !task.trim()) return fail("Task must be a nonempty string.");
  const solutions = typeof solution === "string" ? [solution] : solution;
  if (!Array.isArray(solutions) || !solutions.length || !solutions.every((item) => typeof item === "string" && item.trim())) return fail("Solution must be a nonempty string or array of strings.");
  const errors = record.errors ?? "";
  if (typeof errors !== "string" && !(Array.isArray(errors) && errors.every((item) => typeof item === "string"))) return fail("Errors must be text or an array of strings.");
  const id = record.id;
  if (id !== undefined && typeof id !== "string") return fail("ID must be a string.");
  const sourceId = record.source_item_id;
  if (sourceId !== undefined && typeof sourceId !== "string") return fail("Source item ID must be a string.");
  return { ...(id !== undefined ? { id } : {}), ...(sourceId !== undefined ? { source_item_id: sourceId } : {}), task, solutions: solutions as string[], errors: Array.isArray(errors) ? errors.join("\n") : errors as string };
}

export function parseDataset(text: string, filename: string): DatasetCase[] {
  const source = text.replace(/^\uFEFF/, "");
  let records: unknown[];
  if (filename.toLowerCase().endsWith(".csv")) {
    const [headers, ...rows] = csvRows(source);
    if (!headers) throw new Error("The CSV file is empty.");
    const names = headers.map((header) => header.trim().toLowerCase());
    if (new Set(names).size !== names.length) throw new Error("CSV contains duplicate column names.");
    records = rows.map((row, index) => {
      if (row.length !== headers.length) throw new Error(`CSV row ${index + 2} has ${row.length} values; expected ${headers.length}.`);
      return Object.fromEntries(headers.map((header, at) => [header, row[at]]));
    });
  } else if (filename.toLowerCase().endsWith(".json")) {
    const parsed: unknown = JSON.parse(source);
    records = Array.isArray(parsed) ? parsed : [parsed];
  } else throw new Error("Choose a CSV or JSON file.");
  if (!records.length) throw new Error("The dataset contains no cases.");
  return records.map(caseRecord);
}

export function rubricHandoff(cases: DatasetCase[], source: string | null, synthetic: boolean, project?: string): string {
  return `Use noharm-import-cases and noharm-rubrics${project ? ` for project ${JSON.stringify(project)}` : ""}. Import the dataset below and generate one draft rubric per case.\n\n${source ? `Source file: ${source}` : synthetic ? "Source: synthetic NOHARMKit walkthrough example." : "Source: user-entered dataset."}\n\nDataset:\n${JSON.stringify(cases, null, 2)}`;
}

export function uploadedDatasetHandoff(project: string, sourcePath: string): string {
  return `Use noharm-import-cases and noharm-rubrics for project ${JSON.stringify(project)}. Import ${JSON.stringify(sourcePath)} and generate one draft rubric per case.`;
}
