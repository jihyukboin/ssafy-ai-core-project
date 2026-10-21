import { escapeHtml } from "../utils/html.js";

export function greetingHtml(chat) {
  if (!chat) return "무엇을 도와드릴까요?";
  const logo = /^[0-9A-Z]{6}$/.test(chat.stockCode || "")
    ? `<span class="inline-flex size-[40px] shrink-0 items-center justify-center rounded-full bg-white p-[6px] max-md:size-[32px] max-md:p-[5px]"><img class="size-full object-contain" src="/api/companies/${chat.stockCode}/logo" width="40" height="40" alt="" decoding="async" /></span>`
    : "";
  return `${logo}<span>${escapeHtml(chat.title)}에 대해 무엇이 궁금하신가요?</span>`;
}

export function companyToolsHtml(selected) {
  return `<button id="summary-button" type="button" ${selected ? "" : "hidden"} class="mr-auto rounded-full border border-line px-[12px] py-[7px] text-[12px] text-secondary hover:bg-hover disabled:opacity-50">사업·위험요인 요약</button>`;
}
