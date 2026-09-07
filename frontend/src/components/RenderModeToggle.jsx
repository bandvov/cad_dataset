/** Solid / wireframe toggle -- purely a local rendering preference, no
 * server round-trip. */
export default function RenderModeToggle({ mode, onChange }) {
  return (
    <div className="viewer-mode-group">
      <button
        type="button"
        className={`viewer-mode-btn${mode === "solid" ? " viewer-mode-btn-active" : ""}`}
        onClick={() => onChange("solid")}
        title="Shaded solid"
      >
        Solid
      </button>
      <button
        type="button"
        className={`viewer-mode-btn${mode === "wireframe" ? " viewer-mode-btn-active" : ""}`}
        onClick={() => onChange("wireframe")}
        title="Wireframe"
      >
        Wireframe
      </button>
    </div>
  );
}
