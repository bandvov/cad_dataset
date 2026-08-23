import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// VITE_LLM_SERVICE_URL is now ONLY a dev-server proxy target -- read here
// in Node via loadEnv(), not exposed to the browser bundle. Requests from
// the app go to the same-origin /api/* prefix (see src/api.js); this
// proxy strips that prefix and forwards to wherever llm-service actually
// runs during `npm run dev` (default: host-mapped localhost:8001). The
// production equivalent of this proxy is nginx.conf's `location /api/`.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const llmServiceTarget = env.VITE_LLM_SERVICE_URL || "http://localhost:8001";

  return {
    plugins: [react()],
    server: {
      host: true,
      port: 5173,
      proxy: {
        "/api": {
          target: llmServiceTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
