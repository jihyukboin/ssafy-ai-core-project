export function isChatList(chats) {
  return (
    Array.isArray(chats) &&
    chats.every(
      (chat) =>
        chat &&
        typeof chat.id === "string" &&
        typeof chat.title === "string" &&
        (chat.stockCode === undefined ||
          (typeof chat.stockCode === "string" &&
            /^[0-9A-Z]{6}$/.test(chat.stockCode))) &&
        Array.isArray(chat.messages) &&
        chat.messages.every(
          (message) =>
            message &&
            ["user", "assistant"].includes(message.role) &&
            typeof message.text === "string",
        ),
    )
  );
}
