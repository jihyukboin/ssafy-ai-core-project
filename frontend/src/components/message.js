import { icon } from "./icons.js";
import { toast } from "./toast.js";

const sourceTypes = {
  stock_meta: "기업 메타데이터",
  dart_disclosure: "DART 공시",
  wikipedia: "위키백과",
};
function textElement(tag, text, classes) {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = classes;
  return element;
}
function safeUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
function sourceLink(title, url) {
  const href = safeUrl(url);
  const link = textElement(
    href ? "a" : "span",
    title,
    "font-medium text-primary underline decoration-line underline-offset-4",
  );
  if (href) {
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  }
  return link;
}
export function createMessage(message) {
  if (message.kind === "progress") {
    const element = document.createElement("article");
    element.className =
      "message assistant mb-[24px] rounded-[16px] bg-bubble px-[16px] py-[12px] text-[13px] leading-[22px] text-secondary";
    element.setAttribute("aria-label", "처리 과정");
    element.append(textElement("p", {
      running: "처리 과정 · 진행 중",
      complete: "처리 과정 · 완료",
      error: "처리 과정 · 오류",
      cancelled: "처리 과정 · 중단",
    }[message.status] || "처리 과정", "mb-[8px] font-medium"));
    const steps = document.createElement("ol");
    steps.className = "list-decimal space-y-[4px] pl-[20px]";
    steps.setAttribute("role", "log");
    steps.setAttribute("aria-live", "polite");
    for (const step of message.steps) steps.append(textElement("li", step, ""));
    element.append(steps);
    return element;
  }
  const element = document.createElement("article");
  element.className = `message ${message.role} mb-[30px] text-[15px] leading-[1.85] whitespace-pre-wrap [overflow-wrap:anywhere] ${message.role === "user" ? "ml-auto table max-w-[80%] rounded-[24px] bg-bubble px-[20px] py-[10px] max-md:max-w-[90%]" : "relative py-[8px]"}`;
  element.setAttribute(
    "aria-label",
    message.role === "user" ? "내 메시지" : "AI 응답",
  );
  element.append(
    textElement(
      "div",
      message.text,
      `message-text ${message.error ? "text-red-600" : ""}`,
    ),
  );
  if (message.role !== "assistant" || message.error) return element;
  if (message.kind === "companies") {
    const cards = document.createElement("div");
    cards.className = "mt-[16px] grid gap-[10px]";
    for (const item of message.items || []) {
      if (!/^[0-9A-Z]{6}$/.test(item.stock_code)) continue;
      const card = document.createElement("div");
      card.className =
        "rounded-[16px] border border-line p-[14px] text-[13px] leading-[22px] whitespace-normal";
      const link = document.createElement("a");
      link.href = `/${item.stock_code}`;
      link.dataset.companyCode = item.stock_code;
      link.className =
        "inline-flex items-center gap-[10px] font-medium hover:underline";
      const logo = document.createElement("img");
      logo.src = `/api/companies/${item.stock_code}/logo`;
      logo.width = 28;
      logo.height = 28;
      logo.alt = "";
      logo.className = "size-[28px] rounded-full object-contain";
      link.append(
        logo,
        textElement("span", `${item.name} · ${item.stock_code}`, ""),
      );
      card.append(
        link,
        textElement("p", item.reason, "mt-[6px] text-secondary"),
        textElement(
          "p",
          `${item.market} · 시가총액 ${Number(item.market_cap_krw).toLocaleString("ko-KR")}원 · 기준 ${item.price_as_of}`,
          "mt-[6px] text-[11px] text-secondary",
        ),
        sourceLink("근거 원문", item.source_url),
      );
      cards.append(card);
    }
    element.append(cards);
  } else if (message.sources?.length) {
    const details = document.createElement("details");
    details.className =
      "mt-[16px] rounded-[16px] border border-line p-[14px] text-[13px] leading-[22px] whitespace-normal";
    details.append(
      textElement(
        "summary",
        `답변에 사용한 근거 ${message.sources.length}건`,
        "cursor-pointer font-medium",
      ),
    );
    for (const source of message.sources) {
      const row = document.createElement("div");
      row.className = "mt-[14px] border-t border-line pt-[12px]";
      row.append(
        sourceLink(`[근거 ${source.number}] ${source.title}`, source.url),
        textElement(
          "p",
          `${sourceTypes[source.type] || source.type} · 기준 ${source.basis_date || "미상"}`,
          "mt-[4px] text-[11px] text-secondary",
        ),
        textElement(
          "blockquote",
          source.excerpt,
          "mt-[8px] whitespace-pre-wrap text-secondary",
        ),
      );
      if (source.urls?.length) {
        const originals = document.createElement("div");
        originals.className = "mt-[8px] flex flex-wrap gap-[10px] text-[11px]";
        source.urls.forEach((url, index) =>
          originals.append(sourceLink(`원천 ${index + 1}`, url)),
        );
        row.append(originals);
      }
      details.append(row);
    }
    element.append(details);
  } else
    element.append(
      textElement(
        "p",
        "이 답변에서 인용된 근거가 없습니다.",
        "mt-[12px] text-[12px] text-secondary",
      ),
    );
  if (message.metrics)
    element.append(
      textElement(
        "p",
        `처리 ${message.metrics.elapsed_seconds}초 · 검색 근거 ${message.metrics.retrieved}건 · ${message.metrics.search_method.toUpperCase()}`,
        "mt-[10px] text-[11px] text-secondary",
      ),
    );
  if (message.disclaimer)
    element.append(
      textElement(
        "p",
        message.disclaimer,
        "mt-[12px] text-[11px] leading-[18px] text-secondary",
      ),
    );
  const actions = document.createElement("div");
  actions.className = "message-tools mt-[12px] flex gap-[3px] text-secondary";
  const copy = document.createElement("button");
  copy.className =
    "inline-flex size-[30px] items-center justify-center rounded-[9px] hover:bg-hover [&>svg]:size-[17px]";
  copy.setAttribute("aria-label", "복사");
  copy.innerHTML = icon("copy");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(message.text);
      toast("응답을 복사했습니다.");
    } catch {
      toast("클립보드에 접근할 수 없습니다.");
    }
  });
  actions.append(copy);
  element.append(actions);
  return element;
}
