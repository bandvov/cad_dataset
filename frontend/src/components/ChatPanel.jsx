import { useState, useRef, useEffect } from "react";

export default function ChatPanel({ messages, onSend, isLoading }) {
  const [input, setInput] = useState("");
  const listRef = useRef(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setInput("");
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }

  return (
    <div className="chat-panel">
      <div className="panel-header">Chat</div>

      <div className="chat-messages" ref={listRef}>
        {messages.map((m) => (
          <div
            key={m.id}
            className={`chat-message chat-message-${m.role}${
              m.isError ? " chat-message-error" : ""
            }`}
          >
            <div className="chat-message-role">
              {m.role === "user" ? "You" : "Assistant"}
            </div>
            <div className="chat-message-content">{m.content}</div>
          </div>
        ))}
        {isLoading && (
          <div className="chat-message chat-message-assistant">
            <div className="chat-message-role">Assistant</div>
            <div className="chat-message-content chat-typing">
              Generating…
            </div>
          </div>
        )}
      </div>

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Describe the part you want, or how to change it…"
          rows={3}
          disabled={isLoading}
        />
        <div className="chat-input-row">
          <span className="chat-input-hint">enter to send · shift+enter for newline</span>
          <button
            type="submit"
            className="chat-send-btn"
            disabled={isLoading || !input.trim()}
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
