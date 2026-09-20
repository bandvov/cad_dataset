import { useState, useRef, useEffect } from "react";
import Build123dPromptSelect from "./Build123dPromptSelect";
import {
  BUILD123D_PROMPTS,
  findBuild123dPrompt,
} from "../lib/build123dPrompts";

export default function ChatPanel({ messages, onSend, isLoading }) {
  const [input, setInput] = useState("");
  // Append mode (see llm-service/app/orchestrator.py's APPEND MODE note):
  // when on, the model is asked for only the new feature(s) to add
  // rather than the whole tree -- faster, but only correct for pure
  // additions. Starts off so default behavior is unchanged; per-message,
  // not persisted, since whether an edit is additive varies message to
  // message.
  const [appendMode, setAppendMode] = useState(false);
  const [selectedPrompt, setSelectedPrompt] = useState("");

  const listRef = useRef(null);

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  function handlePromptChange(id) {
    setSelectedPrompt(id);

    if (!id) return;

    const prompt = BUILD123D_PROMPTS.find((item) => item.id === id);
    console.log({ prompt });

    if (prompt) {
      setInput(prompt.prompt);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();

    const trimmed = input?.trim();

    if (!trimmed || isLoading) return;

    onSend(trimmed, appendMode ? "append" : "full");

    setInput("");
    setSelectedPrompt("");
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }
  function handlePromptChange(id) {
    setSelectedPrompt(id);

    if (!id) return;

    const prompt = findBuild123dPrompt(id);

    if (prompt) {
      setInput(prompt.prompt);
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
            {/* elapsed time + prompt/completion token counts for this
                generation, when available (see App.jsx's
                formatGenerateMeta) -- e.g. "2.4s · 812 in / 340 out tok ·
                2 attempts". Absent for messages with nothing to report
                (greetings, undo/redo, structured edits that never called
                the LLM), so this renders nothing rather than an empty
                line. */}
            {m.meta && <div className="chat-message-meta">{m.meta}</div>}
          </div>
        ))}

        {isLoading && (
          <div className="chat-message chat-message-assistant">
            <div className="chat-message-role">Assistant</div>

            <div className="chat-message-content chat-typing">Generating…</div>
          </div>
        )}
      </div>

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <div className="chat-input-prompt-row">
          <Build123dPromptSelect
            value={selectedPrompt}
            onChange={handlePromptChange}
            disabled={isLoading}
          />
        </div>

        <textarea
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setSelectedPrompt("");
          }}
          onKeyDown={handleKeyDown}
          placeholder="Describe the part you want, or how to change it…"
          rows={3}
          disabled={isLoading}
        />

        <div className="chat-input-row">
          <div className="chat-input-left">
            <span className="chat-input-hint">
              enter to send · shift+enter for newline
            </span>

            <button
              type="button"
              className={`chat-mode-toggle${
                appendMode ? " chat-mode-toggle-active" : ""
              }`}
              onClick={() => setAppendMode((v) => !v)}
              disabled={isLoading}
              title={
                appendMode
                  ? "Append mode: generate only new features"
                  : "Full mode: regenerate the whole feature tree"
              }
            >
              {appendMode ? "⚡ Append only" : "Full regenerate"}
            </button>
          </div>
          <button
            type="submit"
            className="chat-send-btn"
            disabled={isLoading || !input}
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
