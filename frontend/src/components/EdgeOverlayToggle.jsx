/** Standalone show/hide-edges toggle -- independent of solid/wireframe
 * mode (wireframe always implies edges; this lets edges show on top of
 * solid shading too). Purely a local rendering preference, no server
 * round-trip -- same pattern as RenderModeToggle. */
export default function EdgeOverlayToggle({ showEdges, onChange, disabled }) {
  return (
    <button
      type="button"
      className={`viewer-mode-btn${showEdges ? " viewer-mode-btn-active" : ""}`}
      onClick={() => onChange(!showEdges)}
      disabled={disabled}
      title={showEdges ? "Hide edges" : "Show edges"}
    >
      Edges
    </button>
  );
}