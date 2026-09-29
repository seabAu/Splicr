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

function toneWav(seconds = 0.2) {
  const sampleRate = 24_000;
  const frames = Math.round(seconds * sampleRate);
  const dataBytes = frames * 2;
  const wav = Buffer.alloc(44 + dataBytes);
  wav.write("RIFF", 0);
  wav.writeUInt32LE(36 + dataBytes, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(sampleRate, 24);
  wav.writeUInt32LE(sampleRate * 2, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(dataBytes, 40);
  for (let index = 0; index < frames; index += 1) {
    wav.writeInt16LE(Math.round(Math.sin(index * 2 * Math.PI * 330 / sampleRate) * 3000), 44 + index * 2);
  }
  return wav;
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

test("Audiogram manages still backgrounds and previews alpha output", async ({ page }) => {
  const runtimeErrors = captureRuntimeErrors(page);
  const created = await page.request.post("/v1/speech/jobs", {
    data: {
      text: "A short browser audiogram source.",
      provider: "fake",
      project_name: "Audiogram browser proof",
    },
  });
  expect(created.ok()).toBeTruthy();
  const sourceId = (await created.json()).id;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const job = await (await page.request.get(`/v1/speech/jobs/${sourceId}`)).json();
    if (job.status === "completed") break;
    await page.waitForTimeout(20);
  }

  await page.getByRole("navigation", { name: "Studio workspaces" })
    .getByRole("button", { name: "Audiogram", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Turn a finished take into a living waveform/ })).toBeVisible();
  await page.getByLabel("Managed still image").setInputFiles({
    name: "cover.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(page.getByLabel("Background mode")).toHaveValue("image");
  await expect(page.locator(".audiogram-background-preview")).toBeVisible();

  await page.getByLabel("Output").selectOption("png_sequence");
  await expect(page.getByLabel("Background mode")).toHaveValue("transparent");
  await expect(page.locator(".audiogram-canvas-shell.is-transparent")).toBeVisible();
  await expect(page.getByRole("button", { name: /8-second proof/ })).toBeDisabled();

  await page.getByText("Geometry, layers, and animation").click();
  await page.getByLabel("Geometry").selectOption("polar");
  await page.getByLabel("Layer mode").selectOption("both");
  await page.getByLabel("Formula field").selectOption("rotation");
  await page.getByLabel("Formula expression").fill("15 * sin(t * 2)");
  await page.getByLabel("Search expression variables and functions").fill("treble");
  await expect(page.getByRole("button", { name: /treble/ })).toBeVisible();
  await expect(page.locator(".audiogram-canvas-shell svg circle")).toBeVisible();
  expect(runtimeErrors).toEqual([]);
});

test("Library batch queues persist frozen work and surface skipped items", async ({ page }) => {
  const runtimeErrors = captureRuntimeErrors(page);
  const createProject = async (name, text) => {
    const created = await page.request.post("/v1/speech/jobs", {
      data: { text, provider: "fake", project_name: name, source_name: `${name}.md` },
    });
    expect(created.ok()).toBeTruthy();
    const id = (await created.json()).id;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const response = await page.request.get(`/v1/speech/jobs/${id}`);
      const job = await response.json();
      if (job.status === "completed") {
        const projects = await (await page.request.get("/v1/studio/projects")).json();
        return projects.find((project) => project.name === name).id;
      }
      await page.waitForTimeout(20);
    }
    throw new Error(`Project seed job ${id} did not finish`);
  };

  const alphaId = await createProject("Batch alpha", "The first browser batch document.");
  const betaId = await createProject("Batch beta", "The second browser batch document.");
  const profileResponse = await page.request.post("/v1/profiles", {
    data: {
      name: "Browser batch profile",
      resource_id: "fake",
      text: "Profile placeholder.",
      model: "fake-model",
      voice: "fake-voice",
      controls: {
        tone: "neutral", pace: "normal", vocal_style: "natural", nonverbal_frequency: "never",
      },
      split_strategy: "semantic",
      chunk_target_mode: "automatic",
      remove_numeric_citations: false,
      variables: { acceptance_slow: true },
    },
  });
  expect(profileResponse.ok()).toBeTruthy();
  const profileId = (await profileResponse.json()).id;

  const navigation = page.getByRole("navigation", { name: "Studio workspaces" });
  await navigation.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByRole("button", { name: "Add Batch alpha to batch" }).click();
  await page.getByRole("button", { name: "Add Batch beta to batch" }).click();
  await page.getByLabel("Queue name").fill("Browser durable queue");
  await page.getByLabel("Render profile").selectOption(profileId);
  await page.getByRole("button", { name: "Queue 2" }).click();
  await expect(page.getByRole("heading", { name: "Browser durable queue" })).toBeVisible();
  await expect(page.locator(".batch-progress")).toBeVisible();
  await page.getByRole("button", { name: "Pause after current" }).click();
  await expect(page.getByRole("button", { name: "Resume queue" })).toBeVisible();
  await page.getByRole("button", { name: "Resume queue" }).click();
  await expect(page.locator(".batch-summary").getByText("2 completed")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Download Batch alpha" })).toBeVisible();

  await page.reload();
  await navigation.getByRole("button", { name: "Library", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Browser durable queue" })).toBeVisible();
  await expect(page.locator(".batch-summary").getByText("2 completed")).toBeVisible();

  const failingProfileResponse = await page.request.post("/v1/profiles", {
    data: {
      name: "Browser failing profile",
      resource_id: "fake",
      text: "Failure profile placeholder.",
      model: "fake-model",
      voice: "fake-voice",
      controls: {
        tone: "neutral", pace: "normal", vocal_style: "natural", nonverbal_frequency: "never",
      },
      split_strategy: "semantic",
      chunk_target_mode: "automatic",
      remove_numeric_citations: false,
      variables: { acceptance_fail: true },
    },
  });
  expect(failingProfileResponse.ok()).toBeTruthy();
  const failingProfileId = (await failingProfileResponse.json()).id;
  const mixed = await page.request.post("/v1/studio/batches", {
    data: {
      name: "Browser mixed-result queue",
      items: [
        { project_id: alphaId, profile_id: failingProfileId },
        { project_id: betaId, profile_id: profileId },
      ],
    },
  });
  expect(mixed.ok()).toBeTruthy();
  await page.reload();
  await navigation.getByRole("button", { name: "Library", exact: true }).click();
  await page.getByLabel("History").selectOption((await mixed.json()).id);
  await expect(page.locator(".batch-summary").getByText("1 failed")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".batch-summary").getByText("1 completed")).toBeVisible();
  await expect(page.locator(".batch-items").getByText(/acceptance batch failure/).first()).toBeVisible();

  expect(runtimeErrors).toEqual([]);
});

test("Convert imports audio and preserves a durable transcription package", async ({ page }) => {
  const runtimeErrors = captureRuntimeErrors(page);
  const navigation = page.getByRole("navigation", { name: "Studio workspaces" });
  await navigation.getByRole("button", { name: "Convert", exact: true }).click();
  await page.getByRole("button", { name: "Transcribe", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Transcribe", exact: true })).toBeVisible();

  await page.locator('.transcription-workspace input[type="file"]').setInputFiles({
    name: "acceptance recording.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("deterministic acceptance audio"),
  });
  await expect(page.getByLabel("Completed take or imported file")).toContainText("acceptance recording.wav");

  await page.getByText("Advanced recognition", { exact: true }).click();
  await page.getByLabel("Word timings").check();
  await page.getByLabel("Per-line timestamps").check();
  const start = page.getByRole("button", { name: "Transcribe audio" });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByText("Latest transcription")).toBeVisible();
  await expect(page.locator(".transcription-job")).toContainText(/transcribing|completed/, {
    timeout: 10_000,
  });
  await expect(page.locator(".transcription-job")).toContainText("100%", { timeout: 15_000 });
  await expect(page.locator(".transcription-facts")).toContainText("0:06 / 0:06");
  await expect(page.getByRole("link", { name: "Transcript" })).toBeVisible();
  await expect(page.getByRole("link", { name: "SRT" })).toBeVisible();
  await expect(page.getByRole("link", { name: "WebVTT" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Guessed chapters" })).toBeVisible();

  const transcriptUrl = await page.getByRole("link", { name: "Transcript" }).getAttribute("href");
  const transcript = await page.request.get(transcriptUrl);
  expect(transcript.ok()).toBeTruthy();
  expect(await transcript.text()).toContain("**[0:00]** Welcome to the acceptance recording.");

  await page.reload();
  await navigation.getByRole("button", { name: "Convert", exact: true }).click();
  await page.getByRole("button", { name: "Transcribe", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Transcription history" })).toBeVisible();
  await expect(page.locator(".transcription-workspace .conversion-history").getByText("acceptance recording.wav")).toBeVisible();
  await expect(page.getByRole("link", { name: "Transcript" })).toBeVisible();

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
  await expect(page.getByRole("button", { name: "Whole chunk" })).toBeVisible();
  await expect(page.getByText(/Reliable sentence timing is unavailable/)).toBeVisible();

  await navigation.getByRole("button", { name: "Publish", exact: true }).click();
  await page.locator("details.publishing-finishing > summary").click();
  await page.getByLabel("Add intro audio").setInputFiles({
    name: "acceptance-intro.wav",
    mimeType: "audio/wav",
    buffer: toneWav(),
  });
  await expect(page.getByLabel("Intro asset")).toContainText("acceptance-intro.wav");
  await page.getByLabel(/Crossfade/).fill("0");
  await page.getByRole("button", { name: "Create finished audio" }).click();
  await expect(page.locator(".publishing-finishing-status.completed")).toBeVisible({ timeout: 20_000 });
  const audioArtifact = page.getByLabel("Audio artifact");
  const finishedOption = audioArtifact.locator("option").filter({ hasText: "Finished" }).first();
  await expect(finishedOption).toBeAttached();
  await audioArtifact.selectOption(await finishedOption.getAttribute("value"));
  await expect(page.locator(".publishing-chapters").getByText("Introduction")).toBeVisible();

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
