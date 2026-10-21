import express from "express";
import { createServer as createHttpServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { createFontPreloader } from "./src/server/font-preloads.js";

const root = fileURLToPath(new URL(".", import.meta.url));
const production = process.argv.includes("--production");
const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:3001";
const app = express();
const server = createHttpServer(app);
app.disable("x-powered-by");
async function companyList() {
  try {
    const response = await fetch(`${backendUrl}/api/companies`, {
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Company API request failed");
    return (await response.json()).items;
  } catch {
    throw Object.assign(new Error("기업정보 API에 연결하지 못했습니다."), {
      status: 503,
    });
  }
}

// Same-origin access for JSON and logos in both development and production.
app.get(/^\/api\/companies(?:\/|$)/, async (request, response) => {
  try {
    const upstream = await fetch(`${backendUrl}${request.originalUrl}`, {
      signal: AbortSignal.timeout(5000),
    });
    response.status(upstream.status);
    for (const header of [
      "content-type",
      "cache-control",
      "etag",
      "last-modified",
    ]) {
      const value = upstream.headers.get(header);
      if (value) response.set(header, value);
    }
    response.send(Buffer.from(await upstream.arrayBuffer()));
  } catch {
    response.status(503).json({ error: "기업정보 API에 연결하지 못했습니다." });
  }
});
const fontCss = await readFile(
  join(
    root,
    "public/fonts/pretendard-gov/pretendardvariable-gov-dynamic-subset.css",
  ),
  "utf8",
);
const fontPreloads = createFontPreloader(fontCss);
let vite;
let productionRenderer;
let productionTemplate;
if (production) {
  productionRenderer = await import("./dist/server/entry-server.js");
  productionTemplate = await readFile(
    join(root, "dist/client/index.html"),
    "utf8",
  );
  app.use(express.static(join(root, "dist/client"), { index: false }));
} else {
  const { createServer } = await import("vite");
  vite = await createServer({
    root,
    server: { middlewareMode: true, hmr: { server } },
    appType: "custom",
  });
  app.use(vite.middlewares);
}
const renderer = () =>
  productionRenderer || vite.ssrLoadModule("/src/entry-server.js");

app.get("/api/rag/status", async (request, response) => {
  try {
    const upstream = await fetch(`${backendUrl}/api/rag/status`, {
      signal: AbortSignal.timeout(10000),
    });
    response.status(upstream.status).json(await upstream.json());
  } catch {
    response.status(503).json({ detail: "백엔드 연결을 확인하세요." });
  }
});
app.post(
  ["/api/chat", "/api/explore"],
  express.json({ limit: "128kb" }),
  async (request, response) => {
    const controller = new AbortController();
    response.on("close", () => controller.abort());
    try {
      const upstream = await fetch(`${backendUrl}${request.path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request.body),
        signal: controller.signal,
      });
      response.status(upstream.status);
      response.set(
        "Content-Type",
        upstream.headers.get("content-type") || "application/x-ndjson",
      );
      response.set("Cache-Control", "no-store");
      response.set("X-Accel-Buffering", "no");
      response.flushHeaders();
      for await (const chunk of upstream.body) {
        if (response.destroyed) break;
        response.write(chunk);
      }
      response.end();
    } catch {
      if (!response.headersSent)
        response
          .status(503)
          .json({ detail: "답변 서버에 연결하지 못했습니다." });
      else if (!response.destroyed)
        response.end(
          JSON.stringify({
            type: "error",
            message: "답변 연결이 중단되었습니다. 다시 질문해 주세요.",
          }) + "\n",
        );
    }
  },
);
app.get(["/", "/:stockCode"], async (request, response) => {
  const stockCode = request.params.stockCode;
  if (stockCode && !/^[0-9A-Z]{6}$/.test(stockCode))
    return response.sendStatus(404);
  const { render, createCompanyChats } = await renderer();
  const companies = await companyList();
  if (
    stockCode &&
    !companies.some((company) => company.stock_code === stockCode)
  )
    return response.sendStatus(404);
  const chats = createCompanyChats(companies);
  let status;
  try {
    status = await (
      await fetch(`${backendUrl}/api/rag/status`, {
        signal: AbortSignal.timeout(10000),
      })
    ).json();
  } catch {
    status = { ready: false, message: "검색 서비스 연결을 확인하세요." };
  }
  const template = production
    ? productionTemplate
    : await vite.transformIndexHtml(
        request.originalUrl,
        await readFile(join(root, "index.html"), "utf8"),
      );
  const html = render(
    template,
    {
      chats,
      currentId: stockCode ? `company-${stockCode}` : null,
      status,
      theme: "light",
    },
    fontPreloads(template, chats),
  );
  response.set("Cache-Control", "no-store").type("html").send(html);
});
app.use((request, response) => response.sendStatus(404));
app.use((error, request, response, next) => {
  if (response.headersSent) return next(error);
  vite?.ssrFixStacktrace(error);
  console.error(error);
  response
    .status(error.status || 500)
    .type("text")
    .send("페이지를 처리하지 못했습니다.");
});

const port = Number(process.env.PORT || 3000);
server.listen(port, "0.0.0.0", () =>
  console.log(`SSR server: http://localhost:${port}`),
);
server.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
  vite?.close();
});
