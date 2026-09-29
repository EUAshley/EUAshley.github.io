"""Auto-editor: timeline planning (pure) and a real render at low resolution."""
import subprocess
from pathlib import Path

import pytest

from engine import config, scoring, video, workflow
from engine.services import ideas, production, publishing, rendering

CFG = video.settings({})
TEXTS = {"hook": "Your phone can do this", "problem": "Typing it every day", "result": "Done automatically",
         "cta": "Follow for more"}


def clip(name, seconds):
    return (Path(name), seconds)


# --- Planning -----------------------------------------------------------------------

def test_plan_orders_segments_and_uses_last_clip_as_result():
    plan = video.plan_video(TEXTS, ["1. Open it", "2. Tap it"], [clip("a", 4), clip("b", 4), clip("r", 5)], CFG)
    assert [s.kind for s in plan.segments] == ["hook", "problem", "step", "step", "result", "cta"]
    assert [s.source.name for s in plan.segments] == ["r", "a", "a", "b", "r", "r"]
    assert plan.segments[1].still == "first" and plan.segments[-1].still == "last"
    assert not plan.warnings


def test_long_clips_are_sped_up_but_capped():
    plan = video.plan_video(TEXTS, ["1. Step"], [clip("a", 30), clip("r", 4)], CFG)
    step = plan.segments[2]
    assert step.speed == CFG["max_speedup"] and step.seconds == 10.0  # 30s / 3x


def test_short_clips_hold_long_enough_to_read():
    long_text = "1. " + " ".join(["word"] * 16)  # ~6s of reading
    plan = video.plan_video(TEXTS, [long_text], [clip("a", 1), clip("r", 4)], CFG)
    step = plan.segments[2]
    assert step.speed == 1.0 and step.seconds == video.read_seconds(long_text, CFG) > 1


def test_missing_clips_is_an_error_and_no_result_clip_is_a_warning():
    with pytest.raises(video.VideoError):
        video.plan_video(TEXTS, ["1", "2", "3"], [clip("a", 3)], CFG)
    plan = video.plan_video(TEXTS, ["1", "2"], [clip("a", 3), clip("b", 3)], CFG)
    assert "reusing the last step clip" in plan.warnings[0]


def test_text_overlay_fits_band(tmp_path):
    from PIL import Image

    out = video.text_overlay(tmp_path / "t.png", "word " * 40, CFG, position="band", size=76)
    bbox = Image.open(out).getbbox()
    assert bbox[3] <= CFG["text_band"]


# --- Rendering (real ffmpeg, small frame for speed) ------------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    small = {**CFG, "width": 360, "height": 640, "text_band": 120, "bottom_margin": 40}
    monkeypatch.setattr(video, "settings", lambda brand: small)
    return tmp_path


def _make_clip(path, seconds, size="390x844"):
    subprocess.run([video.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def _packaged(session):
    idea = ideas.create_idea(session, title="Back Tap screenshot", category="iPhone Features",
                             scores={k: 4 for k in scoring.criteria()},
                             solution_steps="Open Settings > Accessibility\nTouch > Back Tap",
                             benefit="Double-tap the back to screenshot", hook="Tap the back of your iPhone")
    workflow.transition(session, idea, workflow.SELECTED)
    production.generate_script(session, idea)
    production.generate_package(session, idea)
    return idea


def test_render_end_to_end(session, project):
    idea = _packaged(session)
    for i, secs in enumerate([2, 7, 3], 1):
        _make_clip(project / "in.mp4", secs)
        with open(project / "in.mp4", "rb") as f:
            rendering.save_clip(idea, f"RPReplay_{i}.MP4", f.read())
    music = rendering.music_dir(idea.brand.slug)
    music.mkdir(parents=True)
    subprocess.run([video.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                    "-c:a", "aac", str(music / "track.m4a")], check=True)

    r = rendering.render_video(session, idea)
    out = project / r.path
    assert out.exists() and (project / r.cover_path).exists() and r.music == "track.m4a"
    assert out.with_name(out.stem + "-caption.txt").read_text().startswith("Tap the back")
    assert abs(video.probe_duration(out) - r.seconds) < 0.3
    info = subprocess.run([video.ffmpeg_exe(), "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
    assert "360x640" in info and "Audio: aac" in info

    # Rendering is part of what gets reviewed: not allowed once in review
    publishing.submit_for_review(session, idea)
    with pytest.raises(workflow.WorkflowError):
        rendering.render_video(session, idea)
    publishing.review(session, idea, "approved")
    pub = publishing.queue(session, idea, "tiktok")
    assert pub.package.latest_render.id == r.id


def test_render_without_music_has_silent_track(session, project):
    idea = _packaged(session)
    for i in (1, 2, 3):
        _make_clip(project / "in.mp4", 1)
        rendering.save_clip(idea, f"c{i}.mov", (project / "in.mp4").read_bytes())
    r = rendering.render_video(session, idea, music="none")
    info = subprocess.run([video.ffmpeg_exe(), "-hide_banner", "-i", str(project / r.path)],
                          capture_output=True, text=True).stderr
    assert r.music == "" and "Audio: aac" in info


def test_rejects_non_video_upload(session, project):
    idea = _packaged(session)
    with pytest.raises(ValueError):
        rendering.save_clip(idea, "notes.txt", b"hi")
