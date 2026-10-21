import { initChat, newChat } from "./features/chat.js";
import { initNavigation } from "./features/navigation.js";
import { isChatList } from "./data/chat-schema.js";

const state = JSON.parse(document.getElementById("initial-state").textContent);
if (!isChatList(state.chats)) throw new Error("Invalid server state");
initNavigation({ onNewChat: newChat });
initChat(state.chats, state.currentId);
