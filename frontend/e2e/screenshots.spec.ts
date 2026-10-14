import { expect, test } from "@playwright/test";

/**
 * Captures documentation screenshots from the RUNNING stack (real data, no mocks).
 * Enabled only with SCREENSHOTS=1; requires that the referenced runs exist (see docs/demo_script.md).
 *   SCREENSHOTS=1 SHOT_SCENARIO=4 SHOT_RUN=9 PW_CHANNEL=msedge npx playwright test e2e/screenshots.spec.ts
 */
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture docs/screenshots");

const OUT = "../docs/screenshots";
const pages: [string, string, string?][] = [
  ["01_dashboard", "/"],
  ["02_scenarios", "/scenarios"],
  ["03_optimize", "/optimize"],
  ["04_warehouse_gantt", "/gantt", "창고 작업 간트 차트"],
  ["05_docks", "/docks", "도크 적재 타임라인"],
  ["06_routes", "/routes", "배송 경로 도식"],
  ["07_journey", "/journey", "주문 여정 타임라인"],
  ["08_compare", "/compare"],
  ["09_disruptions", "/disruptions"],
  ["10_runs", "/runs"],
];

test("capture screenshots", async ({ page }) => {
  const scenario = Number(process.env.SHOT_SCENARIO ?? 1);
  const run = Number(process.env.SHOT_RUN ?? 0);
  // select scenario/run BEFORE the app boots on every navigation (avoids racing the auto-selection)
  await page.addInitScript(([s, r]) => localStorage.setItem("dilsos.ui", JSON.stringify({ scenarioId: s, runId: r || null })), [scenario, run]);
  await page.goto("/login");
  await page.getByLabel("비밀번호").fill(process.env.E2E_PASSWORD ?? "demo1234");
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page.getByRole("navigation", { name: "주 메뉴" })).toBeVisible();
  for (const [name, path, img] of pages) {
    await page.goto(path);
    if (img) await expect(page.getByRole("img", { name: img })).toBeVisible();
    if (path === "/compare") {
      await page.locator('select[aria-label="문제 유형"]').selectOption("routing");
      await page.getByRole("button", { name: "성공 실행 모두 선택" }).click();
      await expect(page.getByText("알고리즘별 통계 (성공·검증 통과 실행 기준)")).toBeVisible();
    }
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
  }
  // disruption simulator with a recorded event and policy results (SHOT_BD_SCENARIO / SHOT_BD_BASE)
  const bdScenario = Number(process.env.SHOT_BD_SCENARIO ?? 0);
  const bdBase = Number(process.env.SHOT_BD_BASE ?? 0);
  if (bdScenario && bdBase) {
    await page.addInitScript(([s, r]) => localStorage.setItem("dilsos.ui", JSON.stringify({ scenarioId: s, runId: r })), [bdScenario, bdBase]);
    await page.goto("/disruptions");
    await page.getByLabel("기준 실행").selectOption(String(bdBase));
    await page.locator('input[type="radio"]').first().check();
    await expect(page.getByText("추천", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "전/후 비교" }).nth(1).click();
    await expect(page.getByRole("img", { name: "재스케줄 전후 비교 간트" })).toBeVisible();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/09_disruptions.png`, fullPage: true });
  }
});
