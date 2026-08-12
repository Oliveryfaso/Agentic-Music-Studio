import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: new URL(".", import.meta.url).pathname,
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["./src/**/*.test.{ts,tsx}"],
    exclude: ["**/._*"],
  },
});
