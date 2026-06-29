import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 목업 정적 SPA. fixtures/ 의 JSON 을 빌드 타임에 import 한다.
export default defineConfig({
  plugins: [react()],
  server: { port: 5319, strictPort: true },
  preview: { port: 4319, strictPort: true },
});
