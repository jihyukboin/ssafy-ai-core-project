import { icon } from "./icons.js";
import { escapeHtml } from "../utils/html.js";

export function chatListHtml(chats, currentId = null) {
  if (!chats.length)
    return '<p class="empty-chats p-[12px] text-[12px] text-secondary">새로운 대화를 시작해 보세요.</p>';
  return chats
    .map(
      (chat) => `
    <div class="chat-link group/row relative flex h-[44px] items-center rounded-[8px] hover:bg-hover ${currentId === chat.id ? "active bg-hover" : ""}" data-chat-id="${escapeHtml(chat.id)}">
      <${chat.stockCode ? "a" : "button"} ${chat.stockCode ? `href="/${escapeHtml(chat.stockCode)}" ${currentId === chat.id ? 'aria-current="page"' : ""}` : 'type="button"'} class="flex min-w-0 w-full items-center gap-[10px] px-[12px] py-[8px] text-left text-[14px] leading-[20px] ${chat.stockCode ? "" : "group-hover/row:pr-[37px]"}" data-chat-action="open" title="${escapeHtml(chat.title)}">
        ${chat.stockCode && /^[0-9A-Z]{6}$/.test(chat.stockCode) ? `<img class="size-[28px] shrink-0 rounded-full object-contain" src="/api/companies/${chat.stockCode}/logo" width="28" height="28" alt="" loading="lazy" decoding="async" />` : ""}
        <span class="truncate">${escapeHtml(chat.title)}</span>
      </${chat.stockCode ? "a" : "button"}>
      ${chat.stockCode ? "" : `<button class="chat-delete absolute right-[3px] hidden size-[28px] items-center justify-center rounded-[6px] text-secondary group-hover/row:flex group-focus-within/row:flex hover:bg-line hover:text-primary [&>svg]:size-[15px]" data-chat-action="delete" aria-label="${escapeHtml(chat.title)} 삭제">${icon("trash")}</button>`}
    </div>`,
    )
    .join("");
}

export function renderChatList({ chats, currentId }) {
  document.getElementById("chat-list").innerHTML = chatListHtml(
    chats,
    currentId,
  );
}

export function bindChatList({ onOpen, onDelete }) {
  document.getElementById("chat-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-chat-action]");
    if (!button) return;
    if (button.tagName === "A") {
      if (
        event.button !== 0 ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
    }
    const id = button.closest("[data-chat-id]").dataset.chatId;
    if (button.dataset.chatAction === "delete") onDelete(id);
    else onOpen(id);
  });
}
