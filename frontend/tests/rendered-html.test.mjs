import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the PaperDB research-library shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>PaperDB · Shared Research Library<\/title>/i);
  assert.match(html, /Your quantitative research library/);
  assert.match(html, /Supabase library/);
  assert.match(html, /Search titles, abstracts, and summaries/);
  assert.match(html, />Filters</);
  assert.match(html, /Loading papers/);
});

test("uses only browser-safe Supabase settings in the frontend", async () => {
  const [page, layout] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(page, /process\.env\.NEXT_PUBLIC_SUPABASE_URL/);
  assert.match(page, /process\.env\.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY/);
  assert.match(page, /paper_facets/);
  assert.match(page, /search_papers/);
  assert.match(page, /paper_detail/);
  assert.match(page, /Open stored file/);
  assert.doesNotMatch(page, /SUPABASE_(SECRET|SERVICE_ROLE)_KEY/);
  assert.match(layout, /title:\s*"PaperDB · Shared Research Library"/);
});
