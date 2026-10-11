import { expect, test, type Page } from "@playwright/test";

/**
 * The core loop from plan §1.2, end to end:
 *   choose language -> choose scenario -> brief -> roleplay -> report -> drills
 */

async function onboard(page: Page, language: "Korean" | "Japanese" | "German" | "English" = "Korean") {
  await page.goto("/onboarding");
  await page.getByRole("radio", { name: new RegExp(language) }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("radio", { name: /Know the basics/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Travel/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Start practising" }).click();
  await expect(page).toHaveURL(/\/home/);
}

test("landing explains the product and starts onboarding", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Speak first.");
  await page.getByRole("button", { name: "Start a conversation" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
});

test("demo mode is disclosed, not hidden", async ({ page }) => {
  await onboard(page);
  await expect(page.getByRole("status").filter({ hasText: "Demo mode" })).toBeVisible();
});

test("a full typed conversation produces an honest report", async ({ page }) => {
  await onboard(page);
  await page.goto("/scenarios/ko-cafe-order-a1");
  await expect(page.getByRole("heading", { name: "Ordering at a Café" })).toBeVisible();
  await page.getByText("Typing").click();
  await page.getByText("Short").click();
  await page.getByRole("button", { name: "Start conversation" }).click();

  await expect(page).toHaveURL(/\/session\/ses_/);
  // The authored opening line arrives with no model call.
  await expect(page.getByText("안녕하세요! 주문하시겠어요?")).toBeVisible();

  const reply = page.getByLabel("Your reply");
  for (let turn = 1; turn <= 6; turn++) {
    if (await page.getByText("Great job!").isVisible()) break;
    await reply.fill("아이스 아메리카노 한 잔 주세요.");
    await reply.press("Enter");
    // Wait for the reply to land before the next turn.
    await expect(page.getByText(new RegExp(`^${turn}/`)).first()).toBeVisible({ timeout: 15_000 });
  }

  await expect(page).toHaveURL(/\/report/, { timeout: 30_000 });
  await expect(page.getByRole("img", { name: /Overall score: \d+ out of 100/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/≈ A[12]/)).toBeVisible();

  // ADR 0003: a typed session has nothing to estimate pronunciation from,
  // and the report must say "not measured" rather than show a number.
  await expect(page.getByText("Not measured — no audio this session").first()).toBeVisible();

  await page.getByRole("tab", { name: /Pronunciation/ }).click();
  await expect(page.getByText(/estimates from speech-recognition confidence/i)).toBeVisible();

  await page.getByRole("tab", { name: "Transcript" }).click();
  await expect(page.getByText("안녕하세요! 주문하시겠어요?")).toBeVisible();
});

test("IME composition Enter does not send a half-typed Korean word", async ({ page }) => {
  await onboard(page);
  await page.goto("/scenarios/ko-taxi-ride-a1");
  await page.getByText("Typing").click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  const reply = page.getByLabel("Your reply");
  await reply.fill("인사동");
  // keyCode 229 is what Safari reports for an Enter that confirms composition.
  await reply.dispatchEvent("keydown", { key: "Enter", keyCode: 229, isComposing: true });
  await expect(reply).toHaveValue("인사동");
});

test("the library filters by language and level", async ({ page }) => {
  await onboard(page, "German");
  await page.goto("/scenarios");
  await page.getByRole("button", { name: /German/ }).click();
  await page.getByRole("button", { name: "B1" }).click();
  await expect(page.getByRole("link", { name: /Registering Your Address/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /At the Bakery/ })).toHaveCount(0);
});

test("the accent re-tints per language", async ({ page }) => {
  await onboard(page, "Japanese");
  await expect(page.locator("html")).toHaveAttribute("data-lang", "ja");
  await page.goto("/scenarios/de-bakery-a1");
  await expect(page.locator("html")).toHaveAttribute("data-lang", "de");
});

test("a guest is invited to sign up before saving vocabulary", async ({ page }) => {
  await onboard(page);
  await page.goto("/vocab");
  await expect(page.getByText("Keep the words you meet")).toBeVisible();
  await page.getByRole("link", { name: "Create a free account" }).click();
  await expect(page.getByRole("heading", { name: "Save your progress" })).toBeVisible();
});
