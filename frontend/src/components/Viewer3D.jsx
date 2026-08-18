import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

const EXPORT_FORMATS = ["step", "stl", "glb"];

/** Small toolbar of format buttons -- owns its own "which format is
 * currently downloading" state so a slow export only disables itself,
 * not the whole app, and Viewer3D/App.jsx don't need to track it. */
function ExportBar({ onDownload }) {
  const [pending, setPending] = useState(null);

  async function handleClick(format) {
    if (pending) return;
    setPending(format);
    try {
      await onDownload(format);
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="viewer-export-bar">
      {EXPORT_FORMATS.map((format) => (
        <button
          key={format}
          type="button"
          className="viewer-export-btn"
          onClick={() => handleClick(format)}
          disabled={pending !== null}
          title={`Download ${format.toUpperCase()}`}
        >
          {pending === format ? "…" : `↓ ${format.toUpperCase()}`}
        </button>
      ))}
    </div>
  );
}

export default function Viewer3D({ glbBase64, isLoading, hasPart, onDownload }) {
  const mountRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const currentModelRef = useRef(null);
  const [loadError, setLoadError] = useState(null);
  const [bboxLabel, setBboxLabel] = useState(null);

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
        model.traverse((child) => {
          if (child.isMesh) {
            child.material = new THREE.MeshStandardMaterial({
              color: 0xb8bcc4,
              metalness: 0.15,
              roughness: 0.55,
            });
          }
        });

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
  }, [glbBase64]);

  return (
    <div className="viewer-wrap">
      <div className="viewer3d-canvas-mount" ref={mountRef} />

      <div className="viewer-hud">
        <div className="hud-line">CAD COPILOT / VIEWPORT</div>
        {bboxLabel && <div className="hud-line">bbox {bboxLabel}</div>}
      </div>

      {hasPart && !isLoading && <ExportBar onDownload={onDownload} />}

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
