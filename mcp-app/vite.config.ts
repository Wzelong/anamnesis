import { defineConfig } from "vite"
import { fileURLToPath } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": here("./src") },
  },
  build: {
    outDir: here("../backend/mcp_server/ui/assets"),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      input: here("./src/main.tsx"),
      output: {
        entryFileNames: "review.js",
        chunkFileNames: "review-[name].js",
        assetFileNames: "review[extname]",
      },
    },
  },
})
