import * as THREE from "three";

// Angle threshold (degrees) for which triangulation edges EdgesGeometry
// draws. Shared by both wireframe mode and the standalone edge overlay so
// they always look consistent, and so there's one place to retune it if
// curved surfaces (fillets, holes) end up looking noisy/over-faceted.
const EDGE_ANGLE_THRESHOLD = 15;

/** Applies the current render mode (solid/wireframe) AND the independent
 * edge-overlay toggle to a loaded model in place -- swaps materials and
 * adds/removes an EdgesGeometry overlay per mesh. `showEdges` is now
 * decoupled from `mode`: wireframe always implies edges (there's nothing
 * else to see otherwise), but a solid-shaded model can also show edges on
 * top when `showEdges` is true. Pure function over a THREE.Object3D, no
 * component state, so both the initial GLTF-load callback and any
 * toggle-driven effect in Viewer3D can call the exact same logic. */
export function applyRenderMode(model, { mode, showEdges = false } = {}) {
  const wantEdges = mode === "wireframe" || showEdges;

  model.traverse((child) => {
    if (!child.isMesh) return;

    // remove any previously-added edge overlay before re-adding, so
    // toggling back and forth doesn't stack duplicate LineSegments
    const existingEdges = child.children.filter((c) => c.userData.isEdgeOverlay);
    for (const e of existingEdges) {
      child.remove(e);
      e.geometry.dispose();
      e.material.dispose();
    }

    if (mode === "wireframe") {
      child.material = new THREE.MeshStandardMaterial({
        color: 0xb8bcc4,
        metalness: 0.15,
        roughness: 0.55,
        transparent: true,
        opacity: 0.08,
      });
    } else {
      child.material = new THREE.MeshStandardMaterial({
        color: 0xb8bcc4,
        metalness: 0.15,
        roughness: 0.55,
      });
    }

    if (wantEdges) {
      // EdgesGeometry (angle-threshold based) instead of
      // material.wireframe=true -- the latter draws every triangulation
      // edge from build123d's glTF export, which is dense on curved
      // surfaces and looks like noise rather than a clean CAD wireframe.
      const edgesGeo = new THREE.EdgesGeometry(child.geometry, EDGE_ANGLE_THRESHOLD);
      const edges = new THREE.LineSegments(
        edgesGeo,
        new THREE.LineBasicMaterial({ color: 0x4fb8c4 })
      );
      edges.userData.isEdgeOverlay = true;
      child.add(edges);
    }
  });
}