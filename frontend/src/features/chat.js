import { greetingHtml } from "../components/greeting.js";
import { renderChatList, bindChatList } from "../components/chat-list.js";
import { createMessage } from "../components/message.js";
import { streamQuestion } from "../services/api.js";

const $ = (id) => document.getElementById(id);
let chats = [];
let currentId = null;
let homeMessages = [];
let activeRequest = null;
const prompt = $("prompt");
const summaryQuestion = "사업·위험요인 요약을 보여주세요.";
const messages = () =>
  chats.find((chat) => chat.id === currentId)?.messages || homeMessages;

function updateInput() {
  prompt.style.height = prompt.value ? "auto" : "30px";
  if (prompt.value) prompt.style.height = `${Math.min(prompt.scrollHeight, 200)}px`;
  $("send-button").disabled = !prompt.value.trim() || Boolean(activeRequest);
  $("summary-button").disabled = Boolean(activeRequest);
}
function showConversation() {
  $("start-screen").hidden = true;
  $("conversation").hidden = false;
  $("chat-area").classList.add("has-messages");
}
function addMessage(message) {
  $("conversation").append(createMessage(message));
}
function scrollToEnd() {
  $("chat-area").scrollTop = $("chat-area").scrollHeight;
}
function resetChat() {
  activeRequest?.abort();
  activeRequest = null;
  currentId = null;
  $("conversation").replaceChildren();
  $("conversation").hidden = true;
  $("start-screen").hidden = false;
  $("chat-area").classList.remove("has-messages");
  $("greeting").innerHTML = greetingHtml();
  $("summary-button").hidden = true;
  prompt.placeholder =
    "기업명이나 조건으로 찾아보세요 (예: 반도체 관련 코스피 기업)";
  prompt.value = "";
  updateInput();
  $("app").classList.remove("mobile-sidebar-open");
}
export function newChat() {
  resetChat();
  homeMessages = [];
  if (location.pathname !== "/") history.pushState(null, "", "/");
  renderChatList({ chats, currentId });
  prompt.focus();
}
function openChat(id, { updateUrl = true } = {}) {
  const chat = chats.find((item) => item.id === id);
  if (!chat) return;
  resetChat();
  currentId = id;
  if (updateUrl && location.pathname !== `/${chat.stockCode}`)
    history.pushState(null, "", `/${chat.stockCode}`);
  $("greeting").innerHTML = greetingHtml(chat);
  $("summary-button").hidden = false;
  prompt.placeholder = `${chat.title}에 대해 물어보세요`;
  if (chat.messages.length) {
    showConversation();
    chat.messages.forEach(addMessage);
  }
  renderChatList({ chats, currentId });
  requestAnimationFrame(scrollToEnd);
  prompt.focus();
}
async function sendQuestion(mode = "chat") {
  const question = mode === "summary" ? summaryQuestion : prompt.value.trim();
  if (!question || activeRequest) return;
  const chat = chats.find((item) => item.id === currentId);
  const thread = messages();
  const history = thread
    .filter((item) => !item.error && item.kind !== "companies" && item.kind !== "progress")
    .slice(-6)
    .map(({ role, text }) => ({ role, text: text.slice(-4000) }));
  const user = { role: "user", text: question };
  thread.push(user);
  showConversation();
  addMessage(user);
  prompt.value = "";
  const controller = new AbortController();
  activeRequest = controller;
  updateInput();
  const progress = {
    role: "assistant",
    text: "처리 과정",
    kind: "progress",
    status: "running",
    steps: ["질문을 전달하고 있습니다…"],
  };
  thread.push(progress);
  let progressElement = createMessage(progress);
  function renderProgress() {
    const next = createMessage(progress);
    progressElement.replaceWith(next);
    progressElement = next;
  }
  $("conversation").append(progressElement);
  scrollToEnd();
  try {
    const result = await streamQuestion(
      { stock_code: chat?.stockCode || null, question, mode, history },
      (event) => {
        if (controller.signal.aborted) return;
        progress.steps.push(event.message);
        renderProgress();
        scrollToEnd();
      },
      controller.signal,
    );
    if (controller.signal.aborted) return;
    const reply = { role: "assistant", text: result.answer, ...result };
    thread.push(reply);
    progress.status = "complete";
    renderProgress();
    addMessage(reply);
  } catch (error) {
    if (controller.signal.aborted) return;
    progress.status = "error";
    renderProgress();
    const reply = { role: "assistant", text: error.message, error: true };
    thread.push(reply);
    addMessage(reply);
  } finally {
    if (controller.signal.aborted) {
      progress.status = "cancelled";
      renderProgress();
    }
    if (activeRequest === controller) {
      activeRequest = null;
      updateInput();
      scrollToEnd();
      prompt.focus();
    }
  }
}
export function initChat(initialChats, initialId = null) {
  chats = initialChats;
  currentId = initialId;
  bindChatList({ onOpen: openChat, onDelete: () => {} });
  prompt.placeholder = initialId
    ? `${chats.find((chat) => chat.id === initialId)?.title}에 대해 물어보세요`
    : "기업명이나 조건으로 찾아보세요 (예: 반도체 관련 코스피 기업)";
  window.addEventListener("popstate", () => {
    const chat = chats.find(
      (item) => location.pathname === `/${item.stockCode}`,
    );
    if (chat) openChat(chat.id, { updateUrl: false });
    else {
      resetChat();
      renderChatList({ chats, currentId });
    }
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-company-code]");
    if (
      !link ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    const chat = chats.find(
      (item) => item.stockCode === link.dataset.companyCode,
    );
    if (chat) openChat(chat.id);
  });
  prompt.addEventListener("input", updateInput);
  prompt.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!activeRequest) $("composer").requestSubmit();
    }
  });
  $("summary-button").addEventListener("click", () => sendQuestion("summary"));
  $("composer").addEventListener("submit", (event) => {
    event.preventDefault();
    sendQuestion();
  });
  $("composer").addEventListener("click", (event) => {
    if (event.target === $("composer")) prompt.focus();
  });
  updateInput();
}
