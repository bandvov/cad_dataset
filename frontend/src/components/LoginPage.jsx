import { useState } from "react";

export default function LoginPage({ onLogin, onSwitchToSignup, sessionExpired }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await onLogin(email, password);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="auth-title">CAD COPILOT</div>
        <div className="auth-subtitle">Log in</div>

        {sessionExpired && (
          <div className="auth-notice">Your session expired. Log in again.</div>
        )}

        <label className="auth-field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
            disabled={isLoading}
          />
        </label>

        <label className="auth-field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            disabled={isLoading}
          />
        </label>

        {error && <div className="auth-error">{error}</div>}

        <button type="submit" className="auth-submit" disabled={isLoading}>
          {isLoading ? "Logging in…" : "Log in"}
        </button>

        <button
          type="button"
          className="auth-switch"
          onClick={onSwitchToSignup}
          disabled={isLoading}
        >
          Need an account? Sign up
        </button>
      </form>
    </div>
  );
}
