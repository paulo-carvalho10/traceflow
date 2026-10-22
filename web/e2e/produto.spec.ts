import { expect, test } from "@playwright/test";

// Precisam da loja de demonstração mandando traces (docker compose up -d).

test("visitante entra na demonstração, busca traces e abre um waterfall", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ver a demonstração" }).first().click();
  await expect(page).toHaveURL(/\/projects\/1\/dashboard/);
  await page.getByRole("link", { name: "Traces" }).click();
  await expect(page).toHaveURL(/\/projects\/1\/traces/);

  const rows = page.getByRole("row");
  await expect(rows.nth(3)).toBeVisible(); // a loja está mandando: há traces na última hora

  await page.getByPlaceholder("Operação, ex.: /checkout").fill("checkout");
  await page.getByRole("button", { name: "Filtrar" }).click();
  await expect(page).toHaveURL(/operation=checkout/); // o filtro foi para a URL
  await expect(rows.nth(1)).toContainText("POST /checkout");

  await rows.nth(1).getByRole("link").nth(1).click();
  await expect(page).toHaveURL(/\/traces\/[0-9a-f]{32}/);
  const spans = page.getByRole("listitem");
  await expect(spans.first()).toContainText("gateway");
  expect(await spans.count()).toBeGreaterThanOrEqual(5); // uma compra passa por vários serviços

  await spans.filter({ hasText: "orders" }).first().click();
  await expect(page.getByRole("dialog")).toContainText("Tempo próprio");
});

test("o dashboard se atualiza sozinho e leva ao serviço e aos traces dele", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ver a demonstração" }).first().click();
  await expect(page).toHaveURL(/\/projects\/1\/dashboard/);
  await expect(page.getByText("Ao vivo · atualiza a cada segundo")).toBeVisible({ timeout: 20_000 });

  // sem recarregar nada, os números da entrada mudam: chegam retratos novos pelo WebSocket
  const entry = page.getByRole("region", { name: "A entrada do sistema" });
  const before = await entry.innerText();
  await expect.poll(() => entry.innerText(), { timeout: 10_000 }).not.toBe(before);

  await page.getByRole("link", { name: "payments" }).click();
  await expect(page).toHaveURL(/\/services\/payments\?environment=demo/);
  await expect(page.getByRole("cell", { name: /\/charge/ })).toBeVisible({ timeout: 20_000 });

  // a mesma série em tabela: a dica do gráfico nunca é o único caminho até o número
  await page.getByRole("button", { name: "Ver como tabela" }).first().click();
  await expect(page.getByRole("columnheader", { name: "Horário" })).toBeVisible();

  await page.getByRole("link", { name: /Traces que passaram por aqui/ }).click();
  await expect(page).toHaveURL(/through=payments/);
  await expect(page.getByText("Passou por: payments")).toBeVisible();
  // traces de verdade (o esqueleto de carregamento não tem links)
  await expect(page.getByRole("row").nth(1).getByRole("link").first()).toBeVisible({ timeout: 20_000 });
});

test("o mapa desenha quem chama quem a partir dos traces e leva ao serviço", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ver a demonstração" }).first().click();
  await page.getByRole("link", { name: "Mapa de serviços" }).click();
  await expect(page).toHaveURL(/\/projects\/1\/map/);

  // a tabela é a versão em texto do desenho: as ligações da loja, aprendidas pelo pareamento
  await expect(page.getByRole("row", { name: /^Clientes \(entrada\) gateway/ })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("row", { name: /^orders payments/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /^payments bank/ })).toBeVisible();
  // o banco não manda spans: é um nó externo, medido pelas chamadas que chegam nele
  await expect(page.locator(".react-flow__node").filter({ hasText: "externo" })).toContainText("bank");

  await page.locator(".react-flow__node").filter({ hasText: "payments" }).click();
  await expect(page).toHaveURL(/\/services\/payments/);

  await page.goBack();
  await page.getByRole("combobox").nth(1).click();
  await page.getByRole("option", { name: "Última hora" }).click();
  await expect(page.getByRole("columnheader", { name: "Chamadas", exact: true })).toBeVisible({ timeout: 20_000 });
});

test("conta nova cria projeto e chave, e a chave aparece uma vez só", async ({ page }) => {
  await page.goto("/cadastro");
  await page.getByLabel("Nome").fill("Teste E2E");
  await page.getByLabel("E-mail").fill(`e2e-${Date.now()}@exemplo.com`);
  await page.getByLabel("Senha").fill("uma-senha-boa-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page).toHaveURL(/\/projects$/);

  await page.getByRole("button", { name: "Novo projeto" }).click();
  await page.getByLabel("Nome").fill("Projeto E2E");
  await page.getByRole("button", { name: "Criar projeto" }).click();
  await expect(page).toHaveURL(/\/settings\/keys$/);

  await page.getByRole("button", { name: "Nova chave" }).click();
  await page.getByLabel("Nome").fill("produção");
  await page.getByRole("button", { name: "Criar chave" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(/tf_[a-z0-9]{8}_/);
  const fullKey = (await dialog.locator("pre").first().textContent())?.trim() ?? "";
  await page.getByRole("button", { name: "Já copiei" }).click();

  // depois de fechada, a chave inteira não aparece em lugar nenhum da página
  await expect(page.getByRole("cell", { name: "produção" })).toBeVisible();
  await expect(page.getByText(fullKey)).toHaveCount(0);
});

test("sem login, as telas do produto mandam para o login", async ({ page }) => {
  await page.goto("/projects/1/traces");
  await expect(page).toHaveURL(/\/login\?next=%2Fprojects%2F1%2Ftraces/);
});
