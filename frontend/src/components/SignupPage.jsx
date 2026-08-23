import { useState } from "react";

export default function SignupPage({ onSignup, onSwitchToLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setIsLoading(true);
    try {
      await onSignup(email, password);
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
        <div className="auth-subtitle">Create an account</div>

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
            minLength={8}
            disabled={isLoading}
          />
        </label>
        <div className="auth-hint">At least 8 characters.</div>

        {error && <div className="auth-error">{error}</div>}

        <button type="submit" className="auth-submit" disabled={isLoading}>
          {isLoading ? "Creating account…" : "Sign up"}
        </button>

        <button
          type="button"
          className="auth-switch"
          onClick={onSwitchToLogin}
          disabled={isLoading}
        >
          Already have an account? Log in
        </button>
      </form>
    </div>
  );
}
