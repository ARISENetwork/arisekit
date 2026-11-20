import assert from "node:assert/strict";
import test from "node:test";
import { getURLFromRedirectError } from "next/dist/client/components/redirect";
import { isRedirectError } from "next/dist/client/components/redirect-error";
import Home from "../app/page";
import nextConfig from "../next.config";
import { toolkitPrompt } from "../lib/toolkit-prompt";

test("NOHARM coding-agent handoffs select the integrated toolkit and retain the named project", () => {
  const prompt = toolkitPrompt('Use noharm-rubrics for project "alpha". Generate one draft rubric for item "Syn002".');
  assert.match(prompt, /^Work in toolkits\/noharmkit/);
  assert.match(prompt, /Read its AGENTS\.md/);
  assert.match(prompt, /project "alpha"/);
  assert.match(prompt, /item "Syn002"/);
});

test("the root opens the local kit list", () => {
  assert.throws(() => Home(), error => isRedirectError(error) && getURLFromRedirectError(error) === "/kits");
});

test("next.config keeps the legacy redirect without external rewrites", async () => {
  const redirects = await nextConfig.redirects?.();
  assert.deepEqual(redirects, [{ source: "/rubrics", destination: "/noharm/rubrics", permanent: false }]);
  assert.equal(nextConfig.rewrites, undefined);
});
