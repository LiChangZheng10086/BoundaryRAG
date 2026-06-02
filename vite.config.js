import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  root: "frontend",
  base: "/static/",
  build: {
    outDir: "../boundary_rag/web",
    emptyOutDir: true,
    cssCodeSplit: false,
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/knowledge-bases": "http://127.0.0.1:8000",
      "/operation-events": "http://127.0.0.1:8000",
      "/runtime-config": "http://127.0.0.1:8000",
    },
  },
});
