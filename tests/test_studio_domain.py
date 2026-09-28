from pathlib import Path

import pytest

from splicr.studio import (
    Artifact,
    ArtifactKind,
    EngineSessionContext,
    Project,
    RenderPlan,
    RenderSegment,
    Take,
)


def _segment(*, identifier: str = "segment-1", ordinal: int = 0) -> RenderSegment:
    return RenderSegment(
        id=identifier,
        ordinal=ordinal,
        text="A first sentence.",
        source_start=0,
        source_end=17,
        engine_id="gemini",
        voice_id="Kore",
    )


def test_project_plan_take_and_artifact_form_a_stable_hierarchy(tmp_path: Path) -> None:
    project = Project(id="project-1", name="Book", source_text="A first sentence.")
    plan = RenderPlan(
        id="plan-1",
        project_id=project.id,
        revision=1,
        segments=(_segment(),),
    )
    take = Take(
        id="take-1",
        project_id=project.id,
        render_plan_id=plan.id,
        label="First take",
        artifact_ids=("artifact-1",),
    )
    artifact = Artifact(
        id="artifact-1",
        project_id=project.id,
        take_id=take.id,
        kind=ArtifactKind.AUDIO,
        path="artifacts/take-1.wav",
        media_type="audio/wav",
        size_bytes=44,
        sha256="a" * 64,
    )
    context = EngineSessionContext(
        job_id="job-1",
        project_id=project.id,
        render_plan_id=plan.id,
        take_id=take.id,
        work_directory=tmp_path.resolve(),
    )

    assert plan.segments[0].engine_id == "gemini"
    assert take.artifact_ids == (artifact.id,)
    assert context.take_id == artifact.take_id


@pytest.mark.parametrize(
    ("segments", "message"),
    [
        ((), "at least one segment"),
        ((_segment(ordinal=1),), "contiguous and ordered"),
        (
            (_segment(), _segment(ordinal=1)),
            "segment ids must be unique",
        ),
    ],
)
def test_render_plan_rejects_ambiguous_or_unordered_segments(
    segments: tuple[RenderSegment, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RenderPlan(id="plan-1", project_id="project-1", revision=1, segments=segments)


def test_artifact_rejects_invalid_digest() -> None:
    with pytest.raises(ValueError, match="64-character hexadecimal"):
        Artifact(
            id="artifact-1",
            project_id="project-1",
            take_id="take-1",
            kind=ArtifactKind.AUDIO,
            path="take.wav",
            media_type="audio/wav",
            size_bytes=44,
            sha256="not-a-digest",
        )
