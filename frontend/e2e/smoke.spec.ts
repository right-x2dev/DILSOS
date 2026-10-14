import { expect, test, type Page } from "@playwright/test";

/**
 * Spec §10.2 E2E smoke: seed (precondition) → login → scenario → run warehouse baseline → inspect Gantt
 * → run routing → view map → inject disruption → compare results. Real API, real worker, no mocks.
 */
const EMAIL = process.env.E2E_EMAIL ?? "demo@dilsos.local";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo1234";

async function runAlgorithm(page: Page, problemLabel: string, algorithm: string) {
  await page.goto("/optimize");
  await page.getByLabel("문제 유형").selectOption({ label: problemLabel });
  await page.getByLabel("알고리즘").selectOption(algorithm);
  await page.getByLabel("시간 제한(초)").fill("4");
  await page.getByRole("button", { name: "실행 (비동기 큐)" }).click();
  await expect(page.getByText("실행가능 (검증 통과)")).toBeVisible({ timeout: 120_000 });
}

test("seed → login → warehouse run → Gantt → routing → map → disruption → compare", async ({ page }) => {
  // login
  await page.goto("/login");
  await page.getByRole("textbox", { name: "이메일" }).fill(EMAIL);
  await page.getByLabel("비밀번호").fill(PASSWORD);
  await page.getByRole("button", { name: "로그인" }).click();
  await expect(page.getByRole("navigation", { name: "주 메뉴" })).toBeVisible();
  await expect(page.getByRole("note").first()).toContainText("데모 모드");

  // scenario (seeded demo)
  const picker = page.getByLabel("시나리오 선택");
  await expect(picker).toBeVisible();
  const value = await picker.locator("option", { hasText: "normal_day" }).first().getAttribute("value");
  expect(value).toBeTruthy();
  await picker.selectOption(value!);

  // warehouse baseline → Gantt
  await runAlgorithm(page, "창고 (피킹·패킹)", "warehouse_edd");
  await page.getByRole("link", { name: "창고 간트 보기 →" }).click();
  await expect(page.getByRole("img", { name: "창고 작업 간트 차트" })).toBeVisible();

  // routing → map
  await runAlgorithm(page, "배송 경로 (VRPTW)", "routing_insertion");
  await page.getByRole("link", { name: "배송 경로 보기 →" }).click();
  await expect(page.getByRole("img", { name: "배송 경로 도식" })).toBeVisible();
  await expect(page.getByRole("note").filter({ hasText: "데이터 출처" })).toContainText("synthetic_euclidean");

  // integrated base for the disruption
  await runAlgorithm(page, "통합 (창고→도크→배송)", "integrated_sequential");
  const baseText = await page.getByRole("heading", { name: /실행 #\d+/ }).first().textContent();
  const baseId = Number(/#(\d+)/.exec(baseText ?? "")?.[1]);
  expect(baseId).toBeGreaterThan(0);

  // inject disruption → KEEP/PARTIAL/FULL
  await page.goto("/disruptions");
  await page.getByLabel("기준 실행").selectOption(String(baseId));
  await page.getByLabel("이벤트 유형").selectOption("vehicle_breakdown");
  await page.getByLabel("발생 시각").fill("08:30");
  await page.getByRole("button", { name: "이벤트 기록" }).click();
  await expect(page.locator('input[type="radio"]:checked')).toHaveCount(1);
  await page.getByRole("button", { name: "재스케줄 실행" }).click();
  await expect(page.getByText("SUCCEEDED")).toHaveCount(3, { timeout: 180_000 });
  await expect(page.getByText("추천", { exact: true })).toBeVisible();

  // compare results
  await page.goto("/compare");
  await page.locator('select[aria-label="문제 유형"]').selectOption("integrated");
  await page.getByRole("button", { name: "성공 실행 모두 선택" }).click();
  await expect(page.getByText("알고리즘별 통계 (성공·검증 통과 실행 기준)")).toBeVisible();
  await expect(page.getByRole("button", { name: "CSV 다운로드" })).toBeEnabled();
});
