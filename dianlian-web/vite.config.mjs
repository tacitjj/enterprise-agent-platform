import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), "");
  const apiTarget = environment.DIANLIAN_DEV_API_TARGET?.trim();

  if (apiTarget) {
    const targetUrl = new URL(apiTarget);
    if (!["http:", "https:"].includes(targetUrl.protocol)) {
      throw new Error("DIANLIAN_DEV_API_TARGET must use http or https");
    }
  }

  return {
    build: {
      outDir: "dist/client",
    },
    optimizeDeps: {
      include: ["react", "react-dom/client"],
    },
    server: {
      host: "0.0.0.0",
      allowedHosts: ["terminal.local"],
      warmup: {
        clientFiles: ["./src/main.jsx"],
      },
      ...(apiTarget
        ? {
          proxy: {
            "/api": {
              target: apiTarget,
              changeOrigin: true,
            },
          },
        }
        : {}),
    },
    plugins: [react()],
  };
});
