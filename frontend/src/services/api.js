export async function streamQuestion(payload, onStatus, signal) {
  const response = await fetch(
    payload.stock_code ? "/api/chat" : "/api/explore",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "질문을 처리하지 못했습니다. 서버와 입력을 확인하세요.",
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result;
  function consume(line) {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "status") onStatus(event);
    if (event.type === "error") throw new Error(event.message);
    if (event.type === "result") result = event;
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.forEach(consume);
    }
    buffer += decoder.decode();
    consume(buffer);
  } finally {
    reader.releaseLock();
  }
  if (!result)
    throw new Error("답변 연결이 종료되었습니다. 다시 시도해 주세요.");
  return result;
}
