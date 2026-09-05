import { useEffect, useRef } from "react";
import * as THREE from "three";

// BoxGeometry group order is [+X, -X, +Y, -Y, +Z, -Z] -- this array's
// order must match that exactly, since materialIndex from a raycast hit
// indexes straight into it.
const FACES = [
  { label: "RIGHT", axis: [1, 0, 0] },
  { label: "LEFT", axis: [-1, 0, 0] },
  { label: "TOP", axis: [0, 1, 0] },
  { label: "BOTTOM", axis: [0, -1, 0] },
  { label: "FRONT", axis: [0, 0, 1] },
  { label: "BACK", axis: [0, 0, -1] },
];

function makeFaceTexture(label) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#21252c";
  ctx.fillRect(0, 0, 128, 128);
  ctx.strokeStyle = "#3a4048";
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, 124, 124);
  ctx.fillStyle = "#4fb8";
  ctx.font = "600 18px 'IBM Plex Mono', monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, 64, 64);
  return new THREE.CanvasTexture(canvas);
}

/**
 * Corner navigation gizmo (ViewCube) -- the standard CAD orientation aid
 * paired with OrbitControls. Keeps its own tiny scene + orthographic
 * camera; the CUBE stays static and world-axis-aligned, and each frame
 * the gizmo camera is repositioned along the main camera's current
 * viewing direction (same distance-normalized approach, not copying
 * quaternions onto the cube) so the cube always reflects the real
 * orientation. Clicking a face eases the main OrbitControls camera to
 * look at the scene from that face, pivoting around the current
 * controls.target rather than the origin.
 */
export default function ViewCube({ mainCameraRef, mainControlsRef, size = 88 }) {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1.6, 1.6, 1.6, -1.6, 0.1, 10);
    camera.position.set(0, 0, 4);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(size, size);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.domElement.style.cursor = "pointer";
    mount.appendChild(renderer.domElement);

    const materials = FACES.map(
      (f) => new THREE.MeshBasicMaterial({ map: makeFaceTexture(f.label) }),
    );
    const cube = new THREE.Mesh(new THREE.BoxGeometry(1.8, 1.8, 1.8), materials);
    scene.add(cube);
    scene.add(new THREE.AmbientLight(0xffffff, 1));

    // thin colored edge lines on the cube -- X=red/Y=green/Z=blue, same
    // convention as Viewer3D's AxesHelper, so the cube doubles as a
    // legend rather than just an orientation cube
    const edgeGroup = new THREE.Group();
    const edgeMat = (color) => new THREE.LineBasicMaterial({ color });
    const half = 0.95;
    const line = (a, b, color) => {
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(...a),
        new THREE.Vector3(...b),
      ]);
      edgeGroup.add(new THREE.Line(geo, edgeMat(color)));
    };
    line([-half, -half, -half], [half, -half, -half], 0xd9634f); // X, red
    line([-half, -half, -half], [-half, half, -half], 0x4fb87a); // Y, green
    line([-half, -half, -half], [-half, -half, half], 0x4f8fb8); // Z, blue
    scene.add(edgeGroup);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let animId;
    let cancelTween = null;

    function animateCameraTo(direction) {
      const controls = mainControlsRef.current;
      const mainCamera = mainCameraRef.current;
      if (!controls || !mainCamera) return;
      if (cancelTween) cancelTween();

      const target = controls.target.clone();
      const distance = mainCamera.position.distanceTo(target);
      const endPos = target
        .clone()
        .add(new THREE.Vector3(...direction).normalize().multiplyScalar(distance));
      const startPos = mainCamera.position.clone();
      const duration = 350;
      const startTime = performance.now();
      controls.enabled = false;
      let raf;
      let stopped = false;
      cancelTween = () => {
        stopped = true;
        cancelAnimationFrame(raf);
      };

      function step(now) {
        if (stopped) return;
        const t = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - t, 3);
        mainCamera.position.lerpVectors(startPos, endPos, eased);
        mainCamera.lookAt(target);
        controls.update();
        if (t < 1) {
          raf = requestAnimationFrame(step);
        } else {
          controls.enabled = true;
          cancelTween = null;
        }
      }
      raf = requestAnimationFrame(step);
    }

    function handleClick(e) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObject(cube);
      if (hits.length > 0) {
        animateCameraTo(FACES[hits[0].face.materialIndex].axis);
      }
    }
    renderer.domElement.addEventListener("click", handleClick);

    function animate() {
      animId = requestAnimationFrame(animate);
      const mainCamera = mainCameraRef.current;
      const controls = mainControlsRef.current;
      if (mainCamera) {
        const target = controls ? controls.target : new THREE.Vector3();
        const dir = mainCamera.position.clone().sub(target).normalize();
        camera.position.copy(dir.multiplyScalar(4));
        camera.up.copy(mainCamera.up);
        camera.lookAt(0, 0, 0);
      }
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      if (cancelTween) cancelTween();
      cancelAnimationFrame(animId);
      renderer.domElement.removeEventListener("click", handleClick);
      materials.forEach((m) => {
        m.map?.dispose();
        m.dispose();
      });
      cube.geometry.dispose();
      edgeGroup.children.forEach((l) => {
        l.geometry.dispose();
        l.material.dispose();
      });
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [mainCameraRef, mainControlsRef, size]);

  return <div ref={mountRef} style={{ width: size, height: size }} />;
}