import { useEffect, useState } from "react";
import { BUILD123D_PROMPTS } from "../lib/build123dPrompts";

const STORAGE_KEY = "build123d-successful-prompts";
export default function Build123dPromptSelect({
  value,
  onChange,
  disabled = false,
}) {
  const [successfulPrompts, setSuccessfulPrompts] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch {
      return new Set();
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...successfulPrompts]));
    } catch {
      // Ignore localStorage errors.
    }
  }, [successfulPrompts]);
  const selectedPrompt = BUILD123D_PROMPTS.find((item) => item.id === value);
  function toggleSuccessful() {
    if (!selectedPrompt) return;
    setSuccessfulPrompts((current) => {
      const next = new Set(current);
      if (next.has(selectedPrompt.id)) {
        next.delete(selectedPrompt.id);
      } else {
        next.add(selectedPrompt.id);
      }
      return next;
    });
  }
  return (
    <div className="build123d-prompt-select-wrapper">
      {" "}
      <select
        className="build123d-prompt-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {" "}
        <option value="">Build123d example…</option>{" "}
        {BUILD123D_PROMPTS.map((item) => {
          const successful = successfulPrompts.has(item.id);
          return (
            <option key={item.id} value={item.id}>
              {" "}
              {successful ? "✓ " : ""} {item.name}{" "}
            </option>
          );
        })}{" "}
      </select>{" "}
      {selectedPrompt && (
        <button
          type="button"
          className={`build123d-prompt-success ${successfulPrompts.has(selectedPrompt.id) ? "build123d-prompt-success-active" : ""}`}
          onClick={toggleSuccessful}
          disabled={disabled}
          title={
            successfulPrompts.has(selectedPrompt.id)
              ? "Mark as not successful"
              : "Mark test as successful"
          }
          aria-label={
            successfulPrompts.has(selectedPrompt.id)
              ? "Mark test as not successful"
              : "Mark test as successful"
          }
        >
          {" "}
          ✓{" "}
        </button>
      )}{" "}
    </div>
  );
}
