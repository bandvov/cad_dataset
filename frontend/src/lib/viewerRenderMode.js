import * as THREE from "three";

/** Applies the current render mode (solid/wireframe) to a loaded model in
 * place -- swaps materials and adds/removes an EdgesGeometry overlay per
 * mesh. Pure function over a THREE.Object3D, no component state, so both
 * the initial GLTF-load callback and the toggle-driven effect in
 * Viewer3D can call the exact same logic. */
export function applyRenderMode(model, mode) {
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
      // EdgesGeometry (angle-threshold based) instead of
      // material.wireframe=true -- the latter draws every triangulation
      // edge from build123d's glTF export, which is dense on curved
      // surfaces (fillets, holes) and looks like noise rather than a
      // clean CAD wireframe.
      const edgesGeo = new THREE.EdgesGeometry(child.geometry, 15);
      const edges = new THREE.LineSegments(
        edgesGeo,
        new THREE.LineBasicMaterial({ color: 0x4fb8c4 })
      );
      edges.userData.isEdgeOverlay = true;
      child.add(edges);
    } else {
      child.material = new THREE.MeshStandardMaterial({
        color: 0xb8bcc4,
        metalness: 0.15,
        roughness: 0.55,
      });
    }
  });
}
