import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { render, createCompanyChats, isChatList } from "../src/entry-server.js";
import { renderIcons } from "../src/components/icons.js";
import { createFontPreloader } from "../src/server/font-preloads.js";

const template = await readFile(
  new URL("../index.html", import.meta.url),
  "utf8",
);
const companies = [
  { stock_code: "005930", name: "삼성전자" },
  { stock_code: "0126Z0", name: "삼성에피스홀딩스" },
];

test("initial HTML contains chat rows, SVG controls and the exact bootstrap state", () => {
  const state = {
    chats: createCompanyChats(companies),
    theme: "dark",
  };
  const html = render(template, state, "");
  assert.equal((html.match(/data-chat-id=/g) || []).length, 2);
  assert.match(html, /src="\/api\/companies\/005930\/logo"/);
  assert.match(html, /삼성전자/);
  assert.match(html, /src="\/api\/companies\/0126Z0\/logo"/);
  assert.match(html, /data-theme="dark"/);
  assert.match(html, /data-icon="arrowUp"[^<]*><svg/);
  assert.match(html, /data-icon="panel"[^<]*><svg/);
  assert.ok(!html.includes("<!--chat-list-->"));
  const serialized = html.match(
    /<script id="initial-state" type="application\/json">([\s\S]*?)<\/script>/,
  )[1];
  assert.deepEqual(JSON.parse(serialized), state);
});

test("requests create empty conversations and never restore persisted messages", () => {
  const first = createCompanyChats(companies);
  first[0].messages.push({ role: "user", text: "old question" });
  const second = createCompanyChats(companies);
  assert.deepEqual(second[0].messages, []);
  assert.equal(isChatList(second), true);
});

test("company URLs are rendered as links with the selected company in SSR state", () => {
  const state = {
    chats: createCompanyChats(companies),
    currentId: "company-0126Z0",
    theme: "light",
  };
  const html = render(template, state, "");
  assert.match(html, /href="\/005930"/);
  assert.match(html, /href="\/0126Z0" aria-current="page"/);
  assert.match(html, /삼성에피스홀딩스에 대해 무엇이 궁금하신가요\?/);
  assert.match(html, /"currentId":"company-0126Z0"/);
});

test("icons render in attributes containing Tailwind child selectors and multiline closing tags", () => {
  const html = renderIcons(
    '<button class="[&>svg]:size-[22px]" data-icon="panel"></button\n >',
  );
  assert.match(html, /data-icon="panel"><svg/);
});

test("user titles and bootstrap data cannot escape HTML or script boundaries", () => {
  const attack = '</script><img src=x onerror="alert(1)">';
  const state = {
    chats: [
      {
        id: '\"><script>alert(1)</script>',
        title: attack,
        messages: [{ role: "user", text: attack }],
      },
    ],
    theme: "light",
  };
  const html = render(template, state, "");
  assert.ok(!html.includes(attack));
  assert.ok(html.includes("&lt;/script&gt;&lt;img"));
  const serialized = html.match(
    /<script id="initial-state" type="application\/json">([\s\S]*?)<\/script>/,
  )[1];
  assert.deepEqual(JSON.parse(serialized), state);
});

test("font preloads follow unicode ranges rather than loading the whole font", () => {
  const preload = createFontPreloader(
    "src: url(./latin.woff2) format('woff2'); unicode-range: U+0041-005A; src: url(./hangul.woff2) format('woff2'); unicode-range: U+AC00-AC01;",
  );
  assert.match(preload("<p>A</p>", []), /latin.woff2/);
  assert.doesNotMatch(preload("<p>A</p>", []), /hangul.woff2/);
  assert.match(preload("", [{ title: "가" }]), /hangul.woff2/);
});

test("invalid stored and submitted chat data is rejected", () => {
  assert.equal(isChatList([null]), false);
  assert.equal(isChatList([{ id: "a", title: "b", messages: [null] }]), false);
  assert.equal(
    isChatList([
      { id: "a", title: "b", messages: [{ role: "system", text: "bad" }] },
    ]),
    false,
  );
  assert.equal(isChatList([]), true);
});

test("selected company has a circular logo and summary action in SSR", () => {
  const state = {
    chats: createCompanyChats(companies),
    currentId: "company-005930",
    theme: "light",
    status: {
      ready: true,
      companies: 2,
      counts: { stock_meta: 2, disclosure_docs: 10 },
      price_as_of: "2026-10-20",
    },
  };
  const html = render(template, state, "");
  const greeting = html.match(/id="greeting"[\s\S]*?<\/h1>/)[0];
  assert.match(greeting, /rounded-full/);
  assert.match(greeting, /\/api\/companies\/005930\/logo/);
  assert.match(html, /id="summary-button" type="button"\s+class=/);
  assert.match(html, /메타데이터 2건/);
  assert.doesNotMatch(html, /로그인|쿠키 기본 설정/);
});
