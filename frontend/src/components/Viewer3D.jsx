import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import ViewCube from "./ViewCube";

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

const EXPORT_FORMATS = ["step", "stl", "glb"];

/** Format select + a single download trigger, replacing the old
 * one-button-per-format row -- scales better if more formats are added
 * later, and reads as "pick a format, then download" rather than a wall
 * of buttons. Owns its own "selected format" and "download in flight"
 * state so a slow export only disables itself, not the whole toolbar. */
function ExportBar({ onDownload }) {
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

/** Solid / wireframe toggle -- purely a local rendering preference, no
 * server round-trip. */
function RenderModeToggle({ mode, onChange }) {
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

/** Applies the current render mode to a loaded model in place -- swaps
 * materials and adds/removes an EdgesGeometry overlay per mesh. Kept
 * outside the component so both the initial GLTF-load callback and the
 * toggle-driven effect can call the exact same logic. */
function applyRenderMode(model, mode) {
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

export default function Viewer3D({ glbBase64, isLoading, hasPart, onDownload }) {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const currentModelRef = useRef(null);
  const [loadError, setLoadError] = useState(null);
  const [bboxLabel, setBboxLabel] = useState(null);
  const [renderMode, setRenderMode] = useState("solid");

  // one-time scene/camera/renderer/controls setup
  useEffect(() => {
    const mount = mountRef.current;
    const width = mount.clientWidth || 1;
    const height = mount.clientHeight || 1;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x14161a);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100000);
    camera.position.set(150, 130, 150);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controlsRef.current = controls;

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(120, 200, 100);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x4fb8c4, 0.15);
    fill.position.set(-100, 50, -100);
    scene.add(fill);

    // blueprint-style ground grid -- the one deliberate "signature" touch
    // for this view: a drafting-table grid rather than a bare void
    const grid = new THREE.GridHelper(1000, 100, 0x2f6e76, 0x22262c);
    grid.position.y = 0;
    scene.add(grid);

    // XYZ axis gizmo -- THREE.AxesHelper's built-in color convention
    // (X=red, Y=green, Z=blue) matches every other CAD/3D tool.
    scene.add(new THREE.AxesHelper(100));

    let frameId;
    const animate = () => {
      frameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    function handleResize() {
      const w = mount.clientWidth || 1;
      const h = mount.clientHeight || 1;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener("resize", handleResize);
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(mount);

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", handleResize);
      resizeObserver.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, []);

  // load a new GLB whenever one arrives
  useEffect(() => {
    if (!glbBase64 || !sceneRef.current) return;
    setLoadError(null);
    const scene = sceneRef.current;

    let arrayBuffer;
    try {
      arrayBuffer = base64ToArrayBuffer(glbBase64);
    } catch (e) {
      setLoadError("Couldn't decode the exported model.");
      return;
    }

    const loader = new GLTFLoader();
    loader.parse(
      arrayBuffer,
      "",
      (gltf) => {
        if (currentModelRef.current) {
          scene.remove(currentModelRef.current);
        }

        const model = gltf.scene;
        // build123d/OCCT's export_gltf() writes native Z-up coordinates --
        // it has no up-axis/coordinate-system option, so the glTF's Y axis
        // is NOT "up" the way the glTF spec normally implies. This
        // viewport (grid, AxesHelper, camera framing) is Y-up, matching
        // three.js convention, so the loaded model is rotated here to
        // bring build123d's Z-up into this scene's Y-up. Must happen
        // before the bounding-box/camera-framing code below, since that
        // reads the model's transformed (post-rotation) extents.
        model.rotation.x = -Math.PI / 2;
        applyRenderMode(model, renderMode);

        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        model.position.sub(center);
        scene.add(model);
        currentModelRef.current = model;

        setBboxLabel(
          `${size.x.toFixed(1)} × ${size.y.toFixed(1)} × ${size.z.toFixed(1)} mm`
        );

        const maxDim = Math.max(size.x, size.y, size.z, 1);
        const camera = cameraRef.current;
        const dist = maxDim * 2.0;
        camera.position.set(dist, dist * 0.8, dist);
        camera.near = Math.max(maxDim / 500, 0.01);
        camera.far = maxDim * 200;
        camera.updateProjectionMatrix();
        controlsRef.current.target.set(0, 0, 0);
        controlsRef.current.update();
      },
      (err) => {
        console.error("GLTF parse error", err);
        setLoadError("Couldn't render the generated model.");
      }
    );
    // Intentionally NOT depending on renderMode -- a mode change is
    // handled by the effect below re-materialing the already-loaded
    // model in place, not by re-parsing/re-fetching the GLB.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [glbBase64]);

  // re-apply materials when the toggle changes, without touching the
  // GLB data itself -- the model stays loaded, only its appearance changes
  useEffect(() => {
    if (currentModelRef.current) {
      applyRenderMode(currentModelRef.current, renderMode);
    }
  }, [renderMode]);

  return (
    <div className="viewer-wrap">
      <div className="viewer3d-canvas-mount" ref={mountRef} />

      <div className="viewer-hud">
        <div className="hud-line">CAD COPILOT / VIEWPORT</div>
        {bboxLabel && <div className="hud-line">bbox {bboxLabel}</div>}
      </div>

      {hasPart && !isLoading && (
        <div className="viewer-toolbar">
          <RenderModeToggle mode={renderMode} onChange={setRenderMode} />
          <ExportBar onDownload={onDownload} />
        </div>
      )}

      <div className="viewcube-wrap">
        <ViewCube mainCameraRef={cameraRef} mainControlsRef={controlsRef} />
      </div>

      {!hasPart && !isLoading && (
        <div className="viewer-empty">
          <div className="viewer-empty-title">No part loaded</div>
          <div className="viewer-empty-sub">
            Describe what you want to build in the chat panel — a bracket,
            a housing, a flange — and it renders here.
          </div>
        </div>
      )}

      {isLoading && (
        <div className="viewer-loading">
          <div className="spinner" />
        </div>
      )}

      {loadError && <div className="viewer-error">{loadError}</div>}
    </div>
  );
}