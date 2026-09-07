import { useState } from "react";

const EXPORT_FORMATS = ["step", "stl", "glb"];

/** Format select + a single download trigger. Owns its own "selected
 * format" and "download in flight" state so a slow export only disables
 * itself, not the whole toolbar. */
export default function ExportBar({ onDownload }) {
  const [format, setFormat] = useState("glb");
  const [pending, setPending] = useState(false);

  async function handleDownload() {
    if (pending) return;
    setPending(true);
    try {
      await onDownload(format);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="viewer-export-group">
      <select
        className="viewer-export-select"
        value={format}
        onChange={(e) => setFormat(e.target.value)}
        disabled={pending}
        title="Export format"
      >
        {EXPORT_FORMATS.map((f) => (
          <option key={f} value={f}>
            {f.toUpperCase()}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="viewer-export-btn"
        onClick={handleDownload}
        disabled={pending}
        title={`Download ${format.toUpperCase()}`}
      >
        {pending ? "…" : "↓ Download"}
      </button>
    </div>
  );
}
