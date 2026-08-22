import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8000,
    hmr: {
      overlay: true,
    },
  },

  // Build config: enable hashed filenames in production for cache busting.
  build: {
    rollupOptions: {
      output: {
        entryFileNames:
          mode === "production" ? "assets/[name]-[hash].js" : "[name].js",

        chunkFileNames:
          mode === "production" ? "assets/[name]-[hash].js" : "[name].js",

        assetFileNames:
          mode === "production" ? "assets/[name]-[hash].[ext]" : "[name].[ext]",
      },
    },
  },

  plugins: [
    react(),
    mode === "development" && componentTagger(),
  ].filter(Boolean),

  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
