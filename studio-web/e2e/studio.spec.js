import { expect, test } from "@playwright/test";

const WORKSPACES = [
  ["Library", /Your documents, takes, and imported history/],
  ["Dialogue", /Shape a conversation/],
  ["Timeline", /^Timeline$|Shape the take, keep the checkpoints/],
  ["Audiogram", /^Audiogram$|Turn a finished take into a living waveform/],
  ["Publish", /^Publish$/],
  ["Voice studio", /Keep every narrator reproducible/],
  ["Pronunciation", /Teach every engine/],
  ["Components", /^Components$/],
  ["Convert", /^Convert$/],
];

function captureRuntimeErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`page: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

test.beforeEach(async ({ page }) => {
  await page.goto("/studio/");
  await expect(
    page.getByRole("heading", {
      name: /Turn a document into a finished voice performance/,
    }),
  ).toBeVisible();
});

test("every Studio workspace renders without browser errors", async ({ page }) => {
  const runtimeErrors = captureRuntimeErrors(page);
  const navigation = page.getByRole("navigation", { name: "Studio workspaces" });

  for (const [label, heading] of WORKSPACES) {
    await navigation.getByRole("button", { name: label, exact: true }).click();
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
  }

  expect(runtimeErrors).toEqual([]);
});

test("a document can be planned, directed, rendered, played, and reopened", async ({ page }) => {
  const runtimeErrors = captureRuntimeErrors(page);
  const source = page.getByPlaceholder(/Paste the document you want to hear/);
  await source.fill(
    "# Acceptance chapter\n\nThe first sentence verifies document planning. "
      + "The second sentence verifies a complete local render without spending provider quota.",
  );

  await page.getByLabel("Preferred boundary").selectOption("semantic");
  await page.getByLabel(/Remove numeric citations/).check();
  await page.getByLabel("Emotion & tone").selectOption("warm");
  await page.getByLabel("Vocal style").selectOption("conversational");
  await page.getByLabel("Speaking pace").fill("3");
  await page.getByLabel("Non-verbal sounds").fill("1");
  await page.getByLabel("Director's notes").fill("Pause gently after the heading.");

  await page.getByRole("button", { name: "Preview chunks" }).click();
  await expect(page.getByRole("heading", { name: /planned chunks/ })).toBeVisible();
  await expect(page.getByLabel("Planned document chunks")).toBeVisible();

  await page.getByRole("button", { name: "Start new take" }).click();
  await expect(page.getByRole("link", { name: "Download WAV" })).toBeVisible();
  await expect(page.getByLabel("Synthesis progress")).toHaveAttribute("value", "1");
  await expect(page.locator("audio")).toHaveAttribute(
    "src",
    /\/v1\/speech\/jobs\/.+\/audio/,
  );

  const navigation = page.getByRole("navigation", { name: "Studio workspaces" });
  await navigation.getByRole("button", { name: "Library", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Acceptance chapter", exact: true }),
  ).toBeVisible();

  await navigation.getByRole("button", { name: "Timeline", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Shape the take, keep the checkpoints." }),
  ).toBeVisible();
  await expect(
    page.getByLabel("Audio waveform with synthesis segment boundaries"),
  ).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});
