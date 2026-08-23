import { useState } from "react";

export default function ProjectBar({
  projects,
  currentProjectId,
  currentProjectName,
  currentUserEmail,
  onSwitch,
  onCreate,
  onDelete,
  onLogout,
}) {
  const [isOpen, setIsOpen] = useState(false);

  function handleSwitch(id) {
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
            <div className="project-dropdown-backdrop" onClick={() => setIsOpen(false)} />
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
                  <span className="project-dropdown-name">{p.name}</span>
                  <button
                    type="button"
                    className="project-dropdown-delete"
                    onClick={(e) => handleDelete(e, p.id)}
                    title="Delete this part"
                  >
                    ✕
                  </button>
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
