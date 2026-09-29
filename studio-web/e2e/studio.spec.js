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
  await expect(page.getByLabel("Preferred boundary").locator('option[value="h6"]')).toHaveCount(1);
  await page.getByLabel(/Remove numeric citations/).check();
  await page.getByLabel("Emotion & tone").selectOption("warm");
  await page.getByLabel("Vocal style").selectOption("conversational");
  await page.getByLabel("Speaking pace").fill("3");
  await page.getByLabel("Non-verbal sounds").fill("1");
  await page.getByLabel("Director's notes").fill("Pause gently after the heading.");

  const advancedDisclosure = page.locator("details.advanced-controls");
  const advancedSummary = advancedDisclosure.locator("summary");
  await advancedSummary.focus();
  await page.keyboard.press("Enter");
  await expect(advancedDisclosure).toHaveAttribute("open", "");
  await page.getByLabel("Engine").selectOption("alternate-fake");
  await expect(page.getByLabel("Clarity")).toBeVisible();
  await expect(page.getByLabel("Performance variation")).toHaveCount(0);
  await page.getByLabel("Clarity").fill("8");
  await expect(page.getByText("1 customized")).toBeVisible();

  await page.getByLabel("Engine").selectOption("fake");
  await expect(page.getByLabel("Performance variation")).toBeVisible();
  await expect(page.getByLabel("Clarity")).toHaveCount(0);
  await expect(page.getByText("Using recommended defaults")).toBeVisible();
  await page.getByLabel("Performance variation").fill("1.5");
  await expect(page.getByText("Performance variation must be at most 1.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start new take" })).toBeDisabled();
  await page.getByLabel("Performance variation").fill("0.4");
  await page.getByLabel("Delivery mode").selectOption({ label: "dramatic" });
  await expect(page.getByLabel("Repeatable seed")).toBeVisible();
  await page.getByRole("button", { name: "Generate another" }).click();
  await expect(page.getByLabel("Repeatable seed")).not.toHaveValue("");
  await page.getByLabel("Repeatable seed").fill("42");
  await page.getByLabel("Normalize audio").uncheck();
  await expect(page.getByText("4 customized")).toBeVisible();

  const navigation = page.getByRole("navigation", { name: "Studio workspaces" });
  await navigation.getByRole("button", { name: "Library", exact: true }).click();
  await navigation.getByRole("button", { name: "Narrate", exact: true }).click();
  await expect(page.getByLabel("Repeatable seed")).toHaveValue("42");

  const chunkDisclosure = page.locator("details.chunk-advanced");
  await chunkDisclosure.locator("summary").click();
  await page.getByLabel("Target mode").selectOption("characters");
  await page.getByLabel("Target characters").fill("80");

  await page.getByRole("button", { name: "Profiles" }).click();
  const profiles = page.getByRole("dialog", { name: "Profiles" });
  await profiles.getByLabel("Profile name").fill("Acceptance advanced controls");
  await profiles.getByRole("button", { name: "Save profile" }).click();
  await expect(profiles.getByText("Saved Acceptance advanced controls.")).toBeVisible();
  await profiles.getByRole("button", { name: "Close" }).click();

  await page.getByRole("button", { name: "Reset defaults" }).click();
  await page.getByLabel("Target mode").selectOption("automatic");
  await expect(page.getByText("Using recommended defaults")).toBeVisible();
  await page.getByRole("button", { name: "Profiles" }).click();
  const savedProfile = profiles.locator("article").filter({ hasText: "Acceptance advanced controls" });
  await savedProfile.getByRole("button", { name: "Load" }).click();
  await expect(page.getByLabel("Performance variation")).toHaveValue("0.4");
  await expect(page.getByLabel("Repeatable seed")).toHaveValue("42");
  await expect(page.getByLabel("Target mode")).toHaveValue("characters");
  await expect(page.getByLabel("Target characters")).toHaveValue("80");
  await expect(page.getByText("4 customized")).toBeVisible();
  await page.getByLabel("Export filename").fill("Acceptance: narration?");

  await page.getByRole("button", { name: "Preview chunks" }).click();
  await expect(page.getByRole("heading", { name: /planned chunks/ })).toBeVisible();
  await expect(page.getByLabel("Planned document chunks")).toBeVisible();

  await page.getByRole("button", { name: "Start new take" }).click();
  const masterDownload = page.getByRole("link", { name: "Download master WAV" });
  await expect(masterDownload).toBeVisible();
  await expect(masterDownload).toHaveAttribute("download", "Acceptance- narration-.wav");
  await expect(page.getByRole("link", { name: "Export checkpoint WAVs + manifest" })).toBeVisible();
  await expect(page.getByLabel("Synthesis progress")).toHaveAttribute("value", "1");
  await expect(page.locator("audio")).toHaveAttribute(
    "src",
    /\/v1\/speech\/jobs\/.+\/audio/,
  );

  await navigation.getByRole("button", { name: "Library", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Acceptance advanced controls", exact: true }),
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

test("Voice Studio designs a durable identity and generates another take", async ({ page }) => {
  const runtimeErrors = captureRuntimeErrors(page);
  const navigation = page.getByRole("navigation", { name: "Studio workspaces" });
  await navigation.getByRole("button", { name: "Voice studio", exact: true }).click();

  await page.getByRole("button", { name: "Designed voice" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Acceptance designed voice");
  await page.getByLabel("Voice description").fill(
    "A calm, measured documentary narrator with a warm alto register",
  );
  await page.getByRole("spinbutton", { name: "Take", exact: true }).fill("1");
  await page.getByRole("button", { name: "Design voice" }).click();

  await expect(page.getByRole("heading", { name: "Acceptance designed voice" })).toBeVisible();
  await expect(page.getByText("Designed take 1")).toBeVisible();
  await expect(page.getByText("Exact reference transcript")).toBeVisible();
  await expect(page.locator("audio")).toHaveAttribute("src", /\/v1\/studio\/voices\/.+\/reference/);

  await page.getByRole("button", { name: "Generate another take" }).click();
  await expect(page.getByRole("spinbutton", { name: "Take", exact: true })).toHaveValue("2");
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Acceptance designed voice · take 2");
  await page.getByRole("button", { name: "Design voice" }).click();
  await expect(
    page.getByRole("heading", { name: "Acceptance designed voice · take 2" }),
  ).toBeVisible();
  await expect(page.getByText("Designed take 2")).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});
