import { defineConfig, devices } from "@playwright/test";

/**
 * Testes de ponta a ponta: um navegador de verdade usando o TraceFlow inteiro.
 * Precisam do sistema no ar (docker compose up -d) e do front em E2E_BASE_URL.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure", // ao falhar, guarda um "filme" do teste para investigar
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
