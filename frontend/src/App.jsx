import { useCallback, useEffect, useState } from "react";
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

// Plain browser localStorage -- this is a real standalone web app (built
// to files, served by nginx), not a Claude Artifact rendered inline in
// chat, so the artifact sandbox's "no localStorage" restriction doesn't
// apply here.
const PROJECT_KEY = "cad_project_id";
// Step 11: persists { token, user } as one JSON blob so a page reload can
// restore both without an extra round-trip (there's no "get current user
// by token" endpoint, only verify-via-first-authenticated-call). The
// token is an opaque, server-revocable session token (not a JWT), so
// storing it in localStorage is the same trust model as any other
// session-cookie-less SPA -- it's only as sensitive as the session it
// represents, and logout (POST /v1/auth/logout) invalidates it
// server-side, not just locally.
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
  // ---- auth (steps 10-12) ----
  // Token persists across reloads (localStorage, see AUTH_KEY) and is
  // attached as an Authorization header on every authenticated api.js
  // call. A 401 from any of those calls (expired/revoked token) is caught
  // in ONE place -- api.js's authFetch() -- which invokes the handler
  // registered below, rather than every catch block in this file having
  // to recognize "was that a 401?" for itself.
  const [authToken, setAuthTokenState] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [authView, setAuthView] = useState("login"); // "login" | "signup"
  const [authRestored, setAuthRestored] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);

  // Keeps React state, api.js's in-memory token (used to build the
  // Authorization header), and localStorage in sync in one place, so no
  // call site can update one and forget the others.
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

  // Restore a persisted session on first mount, before the project-list
  // effect below (which depends on authToken) can fire.
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

  const handleLogin = useCallback(
    async (email, password) => {
      const { token, user } = await login(email, password);
      setSessionExpired(false);
      applyAuth(token, user);
    },
    [applyAuth],
  );

  const handleSignup = useCallback(
    async (email, password) => {
      const { token, user } = await signup(email, password);
      setSessionExpired(false);
      applyAuth(token, user);
    },
    [applyAuth],
  );

  // Shared by an explicit logout and a global 401: drops auth state, the
  // persisted token, and every piece of project state tied to that
  // session (open part, undo/redo history, chat log) together, so a
  // stale project id can never linger for the NEXT person who logs in on
  // this browser.
  const clearSessionState = useCallback(() => {
    applyAuth(null, null);
    localStorage.removeItem(PROJECT_KEY);
    setProjectId(null);
    clearPartState();
    setMessages([GREETING]);
    setProjects([]);
  }, [applyAuth]);

  const handleLogout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // token may already be invalid/expired server-side -- clear local
      // state regardless, logout should never get the user "stuck"
    }
    clearSessionState();
  }, [clearSessionState]);

  // Global 401 handler (step 12): registered once, invoked by api.js's
  // authFetch() from inside whichever call happened to hit the expired
  // token first. Sets sessionExpired so the login screen can explain why
  // it's showing up again, instead of silently dropping the user there.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setSessionExpired(true);
      clearSessionState();
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSessionState]);

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

  // on mount: populate the project switcher, and restore a previous
  // session if we have one. Gated on authToken (only meaningful once the
  // localStorage-restore effect above has run) so this doesn't fire
  // before a persisted session -- or a fresh login -- has set the
  // Authorization header api.js needs.
  useEffect(() => {
    if (!authToken) return;
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
  }, [authToken, loadProject]);

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
    [projectId],
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
    [projectId, isLoading, loadProject],
  );

  const handleDeleteProject = useCallback(
    async (id) => {
      if (!window.confirm("Delete this part? This can&apos;t be undone.")) return;
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
    [projectId, clearPartState],
  );

  // Renames a project via the switcher dropdown's inline edit field. The
  // project list is the only place a name lives client-side (there's no
  // separate "current project" object) -- patching the list in place
  // keeps currentProjectName (derived below) correct without an extra
  // round-trip.
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

  // ---- auth gate: everything above this is still just hook setup, no
  // rendering, so it's fine for these hooks to exist even while logged
  // out -- React requires hooks to run unconditionally on every render.
  // authRestored avoids a one-frame flash of the login screen while the
  // localStorage-restore effect runs on first mount.
  if (!authRestored) {
    return null;
  }
  if (!authToken) {
    return authView === "login" ? (
      <LoginPage
        onLogin={handleLogin}
        onSwitchToSignup={() => setAuthView("signup")}
        sessionExpired={sessionExpired}
      />
    ) : (
      <SignupPage
        onSignup={handleSignup}
        onSwitchToLogin={() => setAuthView("login")}
      />
    );
  }

  return (
    <div className="app-shell">
      <ProjectBar
        projects={projects}
        currentProjectId={projectId}
        currentProjectName={currentProjectName}
        currentUserEmail={currentUser?.email}
        onSwitch={handleSwitchProject}
        onCreate={handleCreateProject}
        onDelete={handleDeleteProject}
        onRename={handleRenameProject}
        onLogout={handleLogout}
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
