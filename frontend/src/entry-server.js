import { serviceStatusHtml } from "./components/service-status.js";
import { greetingHtml, companyToolsHtml } from "./components/greeting.js";
import { renderIcons } from "./components/icons.js";
import { chatListHtml } from "./components/chat-list.js";
import { serializeState } from "./utils/html.js";

export { createCompanyChats } from "./data/companies.js";
export { isChatList } from "./data/chat-schema.js";

export function render(template, state, fontPreloads) {
  const selected = state.chats.find((chat) => chat.id === state.currentId);
  const html = template
    .replace("<!--theme-->", state.theme)
    .replace("<!--font-preloads-->", fontPreloads)
    .replace("<!--chat-list-->", chatListHtml(state.chats, state.currentId))
    .replace("<!--rag-status-->", serviceStatusHtml(state.status))
    .replace("<!--company-tools-->", companyToolsHtml(selected))
    .replace("무엇을 도와드릴까요?", greetingHtml(selected));
  return renderIcons(html).replace(
    "<!--initial-state-->",
    `<script id="initial-state" type="application/json">${serializeState(state)}</script>`,
  );
}
