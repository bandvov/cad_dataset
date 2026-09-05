import { useCallback, useEffect, useState } from "react";
import { Routes, Route, Navigate, useNavigate, useParams } from "react-router-dom";
import ProjectBar from "./components/ProjectBar";
import ChatPanel from "./components/ChatPanel";
import FeatureTreePanel from "./components/FeatureTreePanel";
import Viewer3D from "./components/Viewer3D";
import LoginPage from "./components/LoginPage";
import SignupPage from "./components/SignupPage";
import {
  login,
  signup,
  logout as apiLogout,
  setAuthToken as setApiAuthToken,
  setUnauthorizedHandler,
  createProject,
  getProject,
  listProjects,
  deleteProject,
  renameProject,
  renderProject,
  downloadExport,
  logDownload,
  generateInProject,
  undoProject,
  redoProject,
  applyEdit,
} from "./api";
import "./styles.css";

// The URL (/projects/:projectId) is now the source of truth for "which
// project is open" -- see ProjectWorkspace below. This key is downgraded
// to a "last opened project" hint only, used to redirect a bare
// "/projects" (or "/") visit somewhere useful; nothing reads it
// authoritatively anymore.
const PROJECT_KEY = "cad_project_id";
// Step 11: persists { token, user } as one JSON blob so a page reload can
// restore both without an extra round-trip. Opaque, server-revocable
// session token -- see frontend/README.md's history for the trust model.
const AUTH_KEY = "cad_auth";

let nextMessageId = 1;
function makeMessage(role, content, extra = {}) {
  return { id: nextMessageId++, role, content, ...extra };
}

const GREETING = makeMessage(
  "assistant",
  "Describe a part and I'll generate it — then tell me what to change and I'll edit it in place.",
);

export default function App() {
  const navigate = useNavigate();

  // ---- auth (steps 10-12) ----
  const [authToken, setAuthTokenState] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [authRestored, setAuthRestored] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);

  const applyAuth = useCallback((token, user) => {
    setAuthTokenState(token);
    setCurrentUser(user);
    setApiAuthToken(token);
    if (token && user) {
      localStorage.setItem(AUTH_KEY, JSON.stringify({ token, user }));
    } else {
      localStorage.removeItem(AUTH_KEY);
    }
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem(AUTH_KEY);
    if (stored) {
      try {
        const { token, user } = JSON.parse(stored);
        if (token && user) applyAuth(token, user);
      } catch {
        localStorage.removeItem(AUTH_KEY); // corrupt entry -- start fresh
      }
    }
    setAuthRestored(true);
  }, [applyAuth]);

  // Where an authenticated caller lands: whatever project was open last
  // time (localStorage hint), or the bare workspace if there isn't one.
  // A pure read, not state -- cheap enough to call inline wherever needed.
  function redirectTarget() {
    const stored = localStorage.getItem(PROJECT_KEY);
    return stored ? `/projects/${stored}` : "/projects";
  }

  const handleLogin = useCallback(
    async (email, password) => {
      const { token, user } = await login(email, password);
      setSessionExpired(false);
      applyAuth(token, user);
      navigate(redirectTarget(), { replace: true });
    },
    [applyAuth, navigate],
  );

  const handleSignup = useCallback(
    async (email, password) => {
      const { token, user } = await signup(email, password);
      setSessionExpired(false);
      applyAuth(token, user);
      navigate("/projects", { replace: true }); // brand-new account, nothing to restore
    },
    [applyAuth, navigate],
  );

  // Shared by an explicit logout and a global 401: drops auth state and
  // the persisted "last project" hint together. Project-specific state
  // (open part, undo/redo history, chat log) now lives in
  // ProjectWorkspace and unmounts on its own once the route below stops
  // rendering it -- nothing to clear here by hand.
  const clearSessionState = useCallback(() => {
    applyAuth(null, null);
    localStorage.removeItem(PROJECT_KEY);
  }, [applyAuth]);

  const handleLogout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // token may already be invalid/expired server-side -- clear local
      // state regardless, logout should never get the user "stuck"
    }
    clearSessionState();
    navigate("/login", { replace: true });
  }, [clearSessionState, navigate]);

  // Global 401 handler (step 12): registered once, invoked by api.js's
  // authFetch() from inside whichever call happened to hit the expired
  // token first.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setSessionExpired(true);
      clearSessionState();
      navigate("/login", { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSessionState, navigate]);

  // authRestored avoids a one-frame flash of the login screen while the
  // localStorage-restore effect runs on first mount.
  if (!authRestored) {
    return null;
  }

  return (
    <Routes>
      <Route
        path="/login"
        element={
          authToken ? (
            <Navigate to={redirectTarget()} replace />
          ) : (
            <LoginPage
              onLogin={handleLogin}
              onSwitchToSignup={() => navigate("/signup")}
              sessionExpired={sessionExpired}
            />
          )
        }
      />
      <Route
        path="/signup"
        element={
          authToken ? (
            <Navigate to={redirectTarget()} replace />
          ) : (
            <SignupPage
              onSignup={handleSignup}
              onSwitchToLogin={() => navigate("/login")}
            />
          )
        }
      />
      <Route
        path="/projects"
        element={
          authToken ? (
            <ProjectWorkspace currentUser={currentUser} onLogout={handleLogout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
      <Route
        path="/projects/:projectId"
        element={
          authToken ? (
            <ProjectWorkspace currentUser={currentUser} onLogout={handleLogout} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
      <Route
        path="*"
        element={<Navigate to={authToken ? redirectTarget() : "/login"} replace />}
      />
    </Routes>
  );
}

// The three-panel app shell (feature tree / viewport / chat) plus
// titlebar. Mounted only once authenticated (see the route guards
// above). `projectId` comes from the URL, not local state -- switching
// projects, creating one, or deleting the current one all navigate
// rather than setState, so the URL is always an accurate, shareable,
// back/forward-able description of what's open.
function ProjectWorkspace({ currentUser, onLogout }) {
  const navigate = useNavigate();
  const { projectId } = useParams(); // undefined on the bare "/projects" route

  const [messages, setMessages] = useState([GREETING]);
  const [projects, setProjects] = useState([]);
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

  const refreshHistory = useCallback(async (pid) => {
    try {
      const [proj, list] = await Promise.all([getProject(pid), listProjects()]);
      setVersionIndex(proj.current_version_index);
      setVersionCount(proj.version_count);
      setCanUndo(proj.can_undo);
      setCanRedo(proj.can_redo);
      setProjects(list);
    } catch {
      // non-fatal -- history/list just won't refresh
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

  // Loads one project's current version + history into state. Used by
  // the URL-driven effect below for every case that used to be "mount
  // restore" vs. "manual switch" -- those are the same operation now,
  // just triggered by a route param changing instead of two separate
  // call sites.
  const loadProject = useCallback(async (id) => {
    const proj = await getProject(id);
    localStorage.setItem(PROJECT_KEY, id);

    setVersionIndex(proj.current_version_index);
    setVersionCount(proj.version_count);
    setCanUndo(proj.can_undo);
    setCanRedo(proj.can_redo);

    if (proj.current) {
      setJsonIr(proj.current.json_ir);
      setStats(proj.current.stats ?? null);
      try {
        const glb = await renderProject(id);
        setGlbBase64(glb);
      } catch (err) {
        console.error("renderProject failed on restore:", err);
        setGlbBase64(null); // tree/stats still show, viewport shows empty state instead of stale model
      }
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

  // Populate the project switcher once per mount.
  useEffect(() => {
    (async () => {
      try {
        setProjects(await listProjects());
      } catch {
        // non-fatal -- switcher just starts empty
      }
    })();
  }, []);

  // The URL is authoritative. No :projectId ("/projects" bare) -> check
  // the last-opened hint and redirect to it, or show the empty state if
  // there isn't one. A :projectId -> load it, for every reason that
  // param could have changed (first mount on a deep link, the switcher,
  // browser back/forward, a fresh navigate() after create/delete).
  useEffect(() => {
    if (!projectId) {
      const stored = localStorage.getItem(PROJECT_KEY);
      if (stored) {
        navigate(`/projects/${stored}`, { replace: true });
      } else {
        clearPartState();
        setMessages([GREETING]);
      }
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    loadProject(projectId)
      .catch((err) => {
        if (cancelled) return;
        // stale/deleted project, or one this user doesn't own -- drop
        // the stale hint and bounce to the bare workspace rather than
        // getting stuck on a route that can never load.
        localStorage.removeItem(PROJECT_KEY);
        setMessages((prev) => [
          ...prev,
          makeMessage("assistant", `Couldn't load that part: ${err.message}`, {
            isError: true,
          }),
        ]);
        navigate("/projects", { replace: true });
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Intentionally keyed on projectId only -- loadProject/navigate are
    // stable-enough callbacks and re-running this on their identity would
    // defeat the point of "load once per URL change."
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const ensureProject = useCallback(async () => {
    if (projectId) return projectId;
    const proj = await createProject();
    localStorage.setItem(PROJECT_KEY, proj.id);
    setProjects((prev) => [proj, ...prev]);
    navigate(`/projects/${proj.id}`);
    return proj.id;
  }, [projectId, navigate]);

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
              { isError: true },
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
    [ensureProject, refreshHistory],
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
        makeMessage(
          "assistant",
          `Reverted to version ${version.version_index + 1}.`,
        ),
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Undo failed: ${err.message}`, {
          isError: true,
        }),
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
        makeMessage(
          "assistant",
          `Reapplied version ${version.version_index + 1}.`,
        ),
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Redo failed: ${err.message}`, {
          isError: true,
        }),
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, canRedo, isLoading, applyVersion, refreshHistory]);

  // Structured-editing fallback (Phase 2 item 4). Deliberately does NOT
  // catch errors here -- FeatureTreePanel's per-item edit form needs the
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
          makeMessage(
            "assistant",
            `Applied edit. (v${result.version_index + 1})`,
          ),
        ]);
      } finally {
        setIsLoading(false);
      }
    },
    [projectId, refreshHistory],
  );

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
    [projectId],
  );

  const handleCreateProject = useCallback(async () => {
    setIsLoading(true);
    try {
      const proj = await createProject("Untitled part");
      localStorage.setItem(PROJECT_KEY, proj.id);
      setProjects((prev) => [proj, ...prev]);
      navigate(`/projects/${proj.id}`);
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
  }, [navigate]);

  const handleSwitchProject = useCallback(
    (id) => {
      if (id === projectId || isLoading) return;
      navigate(`/projects/${id}`);
    },
    [projectId, isLoading, navigate],
  );

  const handleDeleteProject = useCallback(
    async (id) => {
      if (!window.confirm("Delete this part? This can&apos;t be undone.")) return;
      try {
        await deleteProject(id);
        setProjects((prev) => prev.filter((p) => p.id !== id));
        if (id === projectId) {
          localStorage.removeItem(PROJECT_KEY);
          navigate("/projects");
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          makeMessage(
            "assistant",
            `Couldn't delete that part: ${err.message}`,
            {
              isError: true,
            },
          ),
        ]);
      }
    },
    [projectId, navigate],
  );

  // The project list is the only place a name lives client-side.
  const handleRenameProject = useCallback(async (id, name) => {
    try {
      const updated = await renameProject(id, name);
      setProjects((prev) =>
        prev.map((p) => (p.id === id ? { ...p, name: updated.name } : p)),
      );
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        makeMessage("assistant", `Couldn't rename that part: ${err.message}`, {
          isError: true,
        }),
      ]);
    }
  }, []);

  return (
    <div className="app-shell">
      <ProjectBar
        projects={projects}
        currentProjectId={projectId ?? null}
        currentProjectName={currentProjectName}
        currentUserEmail={currentUser?.email}
        onSwitch={handleSwitchProject}
        onCreate={handleCreateProject}
        onDelete={handleDeleteProject}
        onRename={handleRenameProject}
        onLogout={onLogout}
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
        <ChatPanel
          messages={messages}
          onSend={handleSend}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
}
