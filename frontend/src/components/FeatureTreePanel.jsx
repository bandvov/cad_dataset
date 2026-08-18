import { useState } from "react";
import { getEditableFields, applyFieldEdit } from "../lib/featureEdit";

// Technical glyphs (not emoji) standing in for real toolbar icons --
// consistent with the drafting-table register, restrained rather than
// decorative. Each is a simple line-based mark suggesting the operation.
const FEATURE_GLYPHS = {
  Sketch: "▱",
  Extrude: "↑",
  Revolve: "↻",
  Loft: "⧉",
  Sweep: "〰",
  Fillet: "◟",
  Chamfer: "◺",
  Shell: "▭",
  Hole: "○",
  Mirror: "⇄",
  LinearPattern: "⋮⋮⋮",
  CircularPattern: "✳",
};

function featureSummary(feature) {
  switch (feature.feature_type) {
    case "Sketch":
      return `${feature.primitives?.length ?? 0} primitive${
        feature.primitives?.length === 1 ? "" : "s"
      }`;
    case "Extrude":
      return `${feature.amount}mm · ${feature.operation ?? "ADD"}`;
    case "Revolve":
      return `${feature.angle ?? 360}°`;
    case "Loft":
      return `${feature.sources?.length ?? 0} sections`;
    case "Sweep":
      return "along path";
    case "Fillet":
      return `r ${feature.radius}mm`;
    case "Chamfer":
      return `l ${feature.length}mm`;
    case "Shell":
      return `t ${feature.thickness}mm`;
    case "Hole":
      return `${feature.style} · r ${feature.radius}mm`;
    case "Mirror":
      return `about ${feature.plane}`;
    case "LinearPattern":
      return `×${feature.count} · ${feature.spacing}mm`;
    case "CircularPattern":
      return `×${feature.count}`;
    default:
      return "";
  }
}

function formatNumber(n) {
  if (typeof n !== "number") return "—";
  if (Math.abs(n) >= 1000) return n.toFixed(0);
  return n.toFixed(2);
}

/** One feature row. Owns its own expand/draft/pending/error state --
 * App.jsx only sees the final applyEdit(newJsonIr) call, it doesn't need
 * to know about in-progress edits. */
function FeatureItem({ feature, jsonIr, onApplyEdit }) {
  const editableFields = getEditableFields(feature);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState(null); // { [pathKey]: value } while editing
  const [isApplying, setIsApplying] = useState(false);
  const [error, setError] = useState(null);

  function pathKey(path) {
    return path.join(".");
  }

  function startEdit() {
    if (!editableFields) return;
    const initial = {};
    for (const f of editableFields) initial[pathKey(f.path)] = f.value;
    setDraft(initial);
    setError(null);
    setExpanded(true);
  }

  function cancelEdit() {
    setExpanded(false);
    setDraft(null);
    setError(null);
  }

  async function applyEdit() {
    setIsApplying(true);
    setError(null);
    try {
      let next = jsonIr;
      for (const f of editableFields) {
        const raw = draft[pathKey(f.path)];
        const value = Number(raw);
        if (Number.isNaN(value)) {
          throw new Error(`"${f.label}" must be a number`);
        }
        next = applyFieldEdit(next, feature.id, f.path, value);
      }
      await onApplyEdit(next);
      setExpanded(false);
      setDraft(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsApplying(false);
    }
  }

  return (
    <li className="feature-item-wrap">
      <div
        className={`feature-item${editableFields ? " feature-item-editable" : ""}`}
        title={feature.id}
        onClick={editableFields ? (expanded ? cancelEdit : startEdit) : undefined}
      >
        <span className="feature-icon">
          {FEATURE_GLYPHS[feature.feature_type] ?? "•"}
        </span>
        <span className="feature-type">
          {feature.feature_type}
          {editableFields && <span className="feature-edit-hint">edit</span>}
        </span>
        <span className="feature-summary">{featureSummary(feature)}</span>
      </div>

      {expanded && draft && (
        <div className="feature-edit-form">
          {editableFields.map((f) => (
            <label key={pathKey(f.path)} className="feature-edit-field">
              <span>{f.label}</span>
              <input
                type="number"
                step={f.step ?? 0.1}
                min={f.min}
                max={f.max}
                value={draft[pathKey(f.path)]}
                onChange={(e) =>
                  setDraft((prev) => ({ ...prev, [pathKey(f.path)]: e.target.value }))
                }
                disabled={isApplying}
              />
            </label>
          ))}

          {error && <div className="feature-edit-error">{error}</div>}

          <div className="feature-edit-actions">
            <button
              type="button"
              className="feature-edit-btn feature-edit-cancel"
              onClick={cancelEdit}
              disabled={isApplying}
            >
              Cancel
            </button>
            <button
              type="button"
              className="feature-edit-btn feature-edit-apply"
              onClick={applyEdit}
              disabled={isApplying}
            >
              {isApplying ? "Applying…" : "Apply"}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

export default function FeatureTreePanel({
  jsonIr,
  stats,
  versionIndex = -1,
  versionCount = 0,
  canUndo = false,
  canRedo = false,
  onUndo,
  onRedo,
  onApplyEdit,
}) {
  const features = jsonIr?.features ?? [];

  return (
    <div className="feature-tree">
      <div className="panel-header">Feature Tree</div>

      {versionCount > 0 && (
        <div className="history-bar">
          <span className="history-label">
            v{versionIndex + 1} / {versionCount}
          </span>
          <div className="history-buttons">
            <button
              type="button"
              className="history-btn"
              onClick={onUndo}
              disabled={!canUndo}
              title="Undo"
            >
              ‹ Undo
            </button>
            <button
              type="button"
              className="history-btn"
              onClick={onRedo}
              disabled={!canRedo}
              title="Redo"
            >
              Redo ›
            </button>
          </div>
        </div>
      )}

      {features.length === 0 ? (
        <div className="feature-tree-empty">
          No part yet. Describe one in the chat to get started.
        </div>
      ) : (
        <ul className="feature-list">
          {features.map((f) => (
            <FeatureItem
              key={f.id}
              feature={f}
              jsonIr={jsonIr}
              onApplyEdit={onApplyEdit}
            />
          ))}
        </ul>
      )}

      {stats && (
        <div className="stats-panel">
          <div className="panel-header">Stats</div>
          <div className="stats-body">
            <div>
              volume{" "}
              <span className="stat-value">
                {formatNumber(stats.volume)} mm³
              </span>
            </div>
            <div>
              faces <span className="stat-value">{stats.n_faces ?? "—"}</span>
            </div>
            <div>
              edges <span className="stat-value">{stats.n_edges ?? "—"}</span>
            </div>
            <div>
              solids{" "}
              <span className="stat-value">{stats.n_solids ?? "—"}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
