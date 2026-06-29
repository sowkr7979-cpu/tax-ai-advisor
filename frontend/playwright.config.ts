import { defineConfig, devices } from "@playwright/test";

// 빌드된 정적 산출(dist)을 vite preview 로 서빙해 3화면을 검증한다.
// (build 가 dist 를 생성하므로 webServer 가 build → preview 를 순차 실행)
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  use: {
    baseURL: "http://localhost:4319",
    screenshot: "only-on-failure",
    trace: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:4319",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
