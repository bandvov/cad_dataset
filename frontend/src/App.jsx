import { useCallback, useEffect, useState } from "react";
import ProjectBar from "./components/ProjectBar";
import ChatPanel from "./components/ChatPanel";
import FeatureTreePanel from "./components/FeatureTreePanel";
import Viewer3D from "./components/Viewer3D";
import {
  createProject,
  getProject,
  listProjects,
  deleteProject,
  renderProject,
  downloadExport,
  logDownload,
  generateInProject,
  undoProject,
  redoProject,
  applyEdit,
} from "./api";
import "./styles.css";

// Plain browser localStorage -- this is a real standalone web app (built
// to files, served by nginx), not a Claude Artifact rendered inline in
// chat, so the artifact sandbox's "no localStorage" restriction doesn't
// apply here. We only ever store an opaque project id, nothing sensitive.
const PROJECT_KEY = "cad_project_id";

let nextMessageId = 1;
function makeMessage(role, content, extra = {}) {
  return { id: nextMessageId++, role, content, ...extra };
}

const GREETING = makeMessage(
  "assistant",
  "Describe a part and I'll generate it — then tell me what to change and I'll edit it in place."
);

export default function App() {
  const [messages, setMessages] = useState([GREETING]);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [jsonIr, setJsonIr] = useState(null);
  const [glbBase64, setGlbBase64] = useState(null);
  const [stats, setStats] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  // version/history state, kept in sync with the server (the source of
  // truth) after every mutating action rather than derived client-side.
  const [versionIndex, setVersionIndex] = useState(-1);
  const [versionCount, setVersionCount] = useState(0);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const currentProjectName =
    projects.find((p) => p.id === projectId)?.name ?? null;

  // Refreshes both the current project's version/undo-redo state AND the
  // project list (whose ordering is by updated_at, so any mutating action
  // -- generate/undo/redo/apply -- can move the current project to the
  // top). One combined helper so every mutation site only needs one call.
  const refreshHistory = useCallback(async (pid) => {
    try {
      const [proj, list] = await Promise.all([getProject(pid), listProjects()]);
      setVersionIndex(proj.current_version_index);
      setVersionCount(proj.version_count);
      setCanUndo(proj.can_undo);
      setCanRedo(proj.can_redo);
      setProjects(list);
    } catch {
      // non-fatal -- history/list just won't refresh, not worth
      // surfacing as a chat error on top of whatever action triggered this
    }
  }, []);

  const clearPartState = useCallback(() => {
    setJsonIr(null);
    setStats(null);
    setGlbBase64(null);
    setVersionIndex(-1);
    setVersionCount(0);
    setCanUndo(false);
    setCanRedo(false);
  }, []);

  // Shared by mount-restore and manual project switching -- loads a
  // project's current version + history into state. Replaces messages
  // entirely (this is "open a different part," not "continue this chat").
  const loadProject = useCallback(async (id) => {
    const proj = await getProject(id);
    localStorage.setItem(PROJECT_KEY, id);
    setProjectId(id);
    setVersionIndex(proj.current_version_index);
    setVersionCount(proj.version_count);
    setCanUndo(proj.can_undo);
    setCanRedo(proj.can_redo);

    if (proj.current) {
      setJsonIr(proj.current.json_ir);
      setStats(proj.current.stats ?? null);
      const glb = await renderProject(id);
      setGlbBase64(glb);
    } else {
      setJsonIr(null);
      setStats(null);
      setGlbBase64(null);
    }

    const restored = (proj.history ?? []).flatMap((v) => [
      makeMessage("user", v.prompt ?? "(edit)"),
      makeMessage("assistant", `Done. (v${v.version_index + 1})`),
    ]);
    setMessages([GREETING, ...restored]);
  }, []);

  // on mount: populate the project switcher, and restore a previous
  // session if we have one
  useEffect(() => {
    (async () => {
      setIsLoading(true);
      try {
        const list = await listProjects();
        setProjects(list);
      } catch {
        // non-fatal -- switcher just starts empty
      }

      const stored = localStorage.getItem(PROJECT_KEY);
      if (stored) {
        try {
          await loadProject(stored);
        } catch {
          // stale/deleted project -- start fresh rather than block the UI
          localStorage.removeItem(PROJECT_KEY);
        }
      }
      setIsLoading(false);
    })();
  }, [loadProject]);

  const ensureProject = useCallback(async () => {
    if (projectId) return projectId;
    const proj = await createProject();
    localStorage.setItem(PROJECT_KEY, proj.id);
    setProjectId(proj.id);
    setProjects((prev) => [proj, ...prev]);
    return proj.id;
  }, [projectId]);

  const handleSend = useCallback(
    async (prompt) => {
      setMessages((prev) => [...prev, makeMessage("user", prompt)]);
      setIsLoading(true);

      try {
        const pid = await ensureProject();
        const result = await generateInProject({ projectId: pid, prompt });

        if (result.success) {
          setJsonIr(result.json_ir);
          setStats(result.stats ?? null);
          if (result.file_b64) setGlbBase64(result.file_b64);
          await refreshHistory(pid);

          const attemptNote =
            result.attempts > 1 ? ` (${result.attempts} attempts)` : "";
          setMessages((prev) => [
            ...prev,
            makeMessage("assistant", `Done.${attemptNote}`),
          ]);
        } else {
          setMessages((prev) => [
            ...prev,
            makeMessage(
              "assistant",
              `Couldn't produce a valid part: ${
                result.error ?? "unknown error"
              }`,
              { isError: true }
            ),
          ]);
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Request failed: ${err.message}`, {
            isError: true,
          }),
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [ensureProject, refreshHistory]
  );

  const applyVersion = useCallback((version) => {
    setJsonIr(version.json_ir);
    setStats(version.stats ?? null);
    if (version.file_b64) setGlbBase64(version.file_b64);
  }, []);

  const handleUndo = useCallback(async () => {
    if (!projectId || !canUndo || isLoading) return;
    setIsLoading(true);
    try {
      const version = await undoProject(projectId);
      applyVersion(version);
      await refreshHistory(projectId);
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Reverted to version ${version.version_index + 1}.`),
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Undo failed: ${err.message}`, { isError: true }),
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, canUndo, isLoading, applyVersion, refreshHistory]);

  const handleRedo = useCallback(async () => {
    if (!projectId || !canRedo || isLoading) return;
    setIsLoading(true);
    try {
      const version = await redoProject(projectId);
      applyVersion(version);
      await refreshHistory(projectId);
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Reapplied version ${version.version_index + 1}.`),
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Redo failed: ${err.message}`, { isError: true }),
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, canRedo, isLoading, applyVersion, refreshHistory]);

  // Structured-editing fallback (Phase 2 item 4): applies a directly-
  // edited feature tree, bypassing the model. Deliberately does NOT catch
  // errors here -- FeatureTreePanel's per-item edit form needs the
  // rejection to propagate so it can show the error inline next to the
  // field being edited, rather than only in the chat log.
  const handleApplyEdit = useCallback(
    async (newJsonIr) => {
      if (!projectId) throw new Error("no active project");
      setIsLoading(true);
      try {
        const result = await applyEdit({ projectId, jsonIr: newJsonIr });
        setJsonIr(result.json_ir);
        setStats(result.stats ?? null);
        if (result.file_b64) setGlbBase64(result.file_b64);
        await refreshHistory(projectId);
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Applied edit. (v${result.version_index + 1})`),
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [projectId, refreshHistory]
  );

  // Export/download (the other Phase-2-adjacent gap): triggers an actual
  // browser download via a Blob + temporary <a>. Errors surface in chat,
  // consistent with every other action here, rather than a silent failure.
  const handleDownload = useCallback(
    async (format) => {
      if (!projectId) return;
      try {
        const blob = await downloadExport(projectId, format);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `part.${format}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        logDownload(projectId); // fire-and-forget, see api.js docstring
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Download failed: ${err.message}`, {
            isError: true,
          }),
        ]);
      }
    },
    [projectId]
  );

  const handleCreateProject = useCallback(async () => {
    setIsLoading(true);
    try {
      const proj = await createProject("Untitled part");
      localStorage.setItem(PROJECT_KEY, proj.id);
      setProjectId(proj.id);
      clearPartState();
      setMessages([GREETING]);
      setProjects((prev) => [proj, ...prev]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Couldn't create a new part: ${err.message}`, {
          isError: true,
        }),
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [clearPartState]);

  const handleSwitchProject = useCallback(
    async (id) => {
      if (id === projectId || isLoading) return;
      setIsLoading(true);
      try {
        await loadProject(id);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Couldn't load that part: ${err.message}`, {
            isError: true,
          }),
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [projectId, isLoading, loadProject]
  );

  const handleDeleteProject = useCallback(
    async (id) => {
      if (!window.confirm("Delete this part? This can't be undone.")) return;
      try {
        await deleteProject(id);
        setProjects((prev) => prev.filter((p) => p.id !== id));
        if (id === projectId) {
          localStorage.removeItem(PROJECT_KEY);
          setProjectId(null);
          clearPartState();
          setMessages([GREETING]);
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Couldn't delete that part: ${err.message}`, {
            isError: true,
          }),
        ]);
      }
    },
    [projectId, clearPartState]
  );

  return (
    <div className="app-shell">
      <ProjectBar
        projects={projects}
        currentProjectId={projectId}
        currentProjectName={currentProjectName}
        onSwitch={handleSwitchProject}
        onCreate={handleCreateProject}
        onDelete={handleDeleteProject}
      />
      <div className="app-layout">
        <FeatureTreePanel
          jsonIr={jsonIr}
          stats={stats}
          versionIndex={versionIndex}
          versionCount={versionCount}
          canUndo={canUndo}
          canRedo={canRedo}
          onUndo={handleUndo}
          onRedo={handleRedo}
          onApplyEdit={handleApplyEdit}
        />
        <Viewer3D
          glbBase64={glbBase64}
          isLoading={isLoading}
          hasPart={jsonIr !== null}
          onDownload={handleDownload}
        />
        <ChatPanel messages={messages} onSend={handleSend} isLoading={isLoading} />
      </div>
    </div>
  );
}
