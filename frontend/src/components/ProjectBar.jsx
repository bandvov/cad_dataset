import { useState } from "react";

export default function ProjectBar({
  projects,
  currentProjectId,
  currentProjectName,
  currentUserEmail,
  onSwitch,
  onCreate,
  onDelete,
  onRename,
  onLogout,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editValue, setEditValue] = useState("");

  function handleSwitch(id) {
    if (editingId) return; // don't switch rows while one is mid-rename
    setIsOpen(false);
    if (id !== currentProjectId) onSwitch(id);
  }

  function handleCreate() {
    setIsOpen(false);
    onCreate();
  }

  function handleDelete(e, id) {
    e.stopPropagation(); // don't also trigger the row's onClick (switch)
    onDelete(id);
  }

  function startRename(e, project) {
    e.stopPropagation();
    setEditingId(project.id);
    setEditValue(project.name);
  }

  function cancelRename() {
    setEditingId(null);
    setEditValue("");
  }

  function commitRename(id) {
    const trimmed = editValue.trim();
    const current = projects.find((p) => p.id === id);
    if (trimmed && current && trimmed !== current.name) {
      onRename(id, trimmed);
    }
    setEditingId(null);
    setEditValue("");
  }

  function handleRenameKeyDown(e, id) {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename(id);
    } else if (e.key === "Escape") {
      e.preventDefault();
      cancelRename();
    }
  }

  return (
    <div className="titlebar">
      <div className="titlebar-brand">CAD COPILOT</div>

      <div className="project-switcher">
        <button
          type="button"
          className="project-switcher-btn"
          onClick={() => setIsOpen((o) => !o)}
        >
          {currentProjectName ?? "No part open"}
          <span className="chevron">{isOpen ? "▴" : "▾"}</span>
        </button>

        {isOpen && (
          <>
            <div
              className="project-dropdown-backdrop"
              onClick={() => {
                setIsOpen(false);
                cancelRename();
              }}
            />
            <div className="project-dropdown">
              {projects.length === 0 && (
                <div className="project-dropdown-empty">No parts yet</div>
              )}
              {projects.map((p) => (
                <div
                  key={p.id}
                  className={`project-dropdown-item${
                    p.id === currentProjectId ? " project-dropdown-item-active" : ""
                  }`}
                  onClick={() => handleSwitch(p.id)}
                >
                  {editingId === p.id ? (
                    <input
                      type="text"
                      className="project-dropdown-rename-input"
                      value={editValue}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => handleRenameKeyDown(e, p.id)}
                      onBlur={() => commitRename(p.id)}
                    />
                  ) : (
                    <span className="project-dropdown-name">{p.name}</span>
                  )}

                  <div className="project-dropdown-item-actions">
                    {editingId !== p.id && (
                      <button
                        type="button"
                        className="project-dropdown-rename"
                        onClick={(e) => startRename(e, p)}
                        title="Rename this part"
                      >
                        ✎
                      </button>
                    )}
                    <button
                      type="button"
                      className="project-dropdown-delete"
                      onClick={(e) => handleDelete(e, p.id)}
                      title="Delete this part"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              ))}
              <div className="project-dropdown-new" onClick={handleCreate}>
                + New part
              </div>
            </div>
          </>
        )}
      </div>

      {currentUserEmail && (
        <div className="titlebar-user">
          <span className="titlebar-user-email" title={currentUserEmail}>
            {currentUserEmail}
          </span>
          <button
            type="button"
            className="titlebar-logout-btn"
            onClick={onLogout}
            title="Log out"
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
