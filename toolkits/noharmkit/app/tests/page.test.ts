import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

test("old run viewer pages redirect to mission control", () => {
  const dir = path.join(process.cwd(), "app", "noharm", "runs");
  const pages = existsSync(dir) ? (readdirSync(dir, { recursive: true }) as string[]).filter((f) => f.endsWith("page.tsx")) : [];
  assert.ok(pages.includes("page.tsx") && pages.includes(path.join("[caseset]", "page.tsx")), `missing run pages: ${pages.join(", ")}`);
  for (const file of pages) {
    const source = readFileSync(path.join(dir, file), "utf8");
    assert.match(source, /[Rr]edirect/, file);
    if (file.includes("[caseset]")) {
      assert.match(source, /if \(\(await getCurrent\(\)\)\?\.bench\.name !== caseset\) notFound\(\);/, file);
      assert.doesNotMatch(source, /permanentRedirect/, "Project-dependent redirects must not be cached permanently.");
    }
  }
  assert.match(readFileSync(path.join(dir, "page.tsx"), "utf8"), /permanentRedirect\("\/noharm\/dashboard"\)/);
  const route = readFileSync(path.join(dir, "[caseset]", "[caseId]", "table", "[version]", "page.tsx"), "utf8");
  assert.match(route, /redirect/);
  assert.match(route, /runsRedirect/);
});

// Source check until a render test covers the hidden committee ratings.
test("the answer-table editor saves to the project table route and hides stale committee ratings", () => {
  const editor = readFileSync(path.join(process.cwd(), "components", "AnswerTableEditor.tsx"), "utf8");
  assert.match(editor, /const endpoint = "\/api\/runs\/table";/);
  assert.match(editor, /<CommitteeNote rating=\{rating\} \/>/);
  assert.match(editor, /data-save-target/);
  assert.match(editor, /source && loaded\?\.notice/);
  assert.match(editor, /const \[ratingsStale, setRatingsStale\] = useState\(false\);/);
  assert.match(editor, /setRatingsStale\(true\);/);
  assert.match(editor, /Committee ratings hidden: Decisions changed since load\./);
  assert.match(editor, /if \(!rating && !cap\) return null;/);
});
