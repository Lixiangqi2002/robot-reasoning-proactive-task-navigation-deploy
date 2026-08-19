from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import random
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import streamlit as st
from PIL import Image


APP_DIR = Path(__file__).resolve().parent
DEFAULT_STATIC_DATA_ROOT = APP_DIR / "assets"
DEFAULT_EXTERNAL_DATA_ROOT = Path("/media/selina-xiangqi/New Volume/dsg_dataset/user_study_data")
DATA_ROOT = Path(
    os.environ.get(
        "DSG_USER_STUDY_DATA_ROOT",
        str(DEFAULT_STATIC_DATA_ROOT if DEFAULT_STATIC_DATA_ROOT.exists() else DEFAULT_EXTERNAL_DATA_ROOT),
    )
)
RESPONSE_CSV = Path(
    os.environ.get(
        "DSG_USER_STUDY_RESPONSE_CSV",
        "streamlit_user_study/responses/user_study_responses.csv",
    )
)
GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
DEFAULT_SUPABASE_TABLE = "user_study_responses"

RANDOMIZE_OPTION_ORDER = os.environ.get("DSG_RANDOMIZE_OPTION_ORDER", "1") != "0"

LIKERT_REASONABLE = [
    "1 Not reasonable at all",
    "2 Slightly reasonable",
    "3 Somewhat reasonable",
    "4 Reasonable",
    "5 Very reasonable",
]
LIKERT_AGREE = [
    "1 Strongly disagree",
    "2 Disagree",
    "3 Not sure",
    "4 Agree",
    "5 Strongly agree",
]
LIKERT_TOO_LOW_HIGH = [
    "1 Much too low",
    "2 Slightly too low",
    "3 About right",
    "4 Slightly too high",
    "5 Much too high",
]
LIKERT_POOR_WELL = [
    "1 Very poorly",
    "2 Poorly",
    "3 Acceptably",
    "4 Well",
    "5 Very well",
]
LIKERT_INAPPROPRIATE_APPROPRIATE = [
    "1 Very inappropriate",
    "2 Inappropriate",
    "3 Acceptable",
    "4 Appropriate",
    "5 Very appropriate",
]
LIKERT_UNSAFE_SAFE = [
    "1 Very unsafe",
    "2 Unsafe",
    "3 Acceptable",
    "4 Safe",
    "5 Very safe",
]
LIKERT_POOR_GOOD = [
    "1 Very poor",
    "2 Poor",
    "3 Acceptable",
    "4 Good",
    "5 Very good",
]
LIKERT_UNDER_OVER_REACT = [
    "1 Strongly underreacts",
    "2 Slightly underreacts",
    "3 About right",
    "4 Slightly overreacts",
    "5 Strongly overreacts",
]
SCORE_1_TO_10 = [str(i) for i in range(1, 11)]

GREEN = "#2fbf71"
RED = "#ff5a5f"
ROBOT_ROUTE_COLORS = {
    "A": "orange",
    "B": "cyan",
    "C": "green",
}

DISPLAY_LABELS = {
    "local_hazard": "something nearby that may need attention",
    "object_motion_risk": "a moving or unstable object",
    "collision_risk": "possible contact with a person or object",
    "fall_risk": "a possible fall or dropped object",
    "blocked_access": "blocked access or blocked movement",
    "interaction_interruption": "possible interruption of the person's activity",
    "none": "no clear concern",
    "unclear": "unclear concern",
    "no_interaction": "no clear interaction",
    "upper_body": "upper-body contact or movement",
    "lower_body": "lower-body contact or movement",
    "increase_human_safety_margin": "keep extra safety space around the person",
    "approach_visibility_continuity": "stay visible while approaching",
    "avoid_near_human": "avoid getting too close to people nearby",
    "notify_nearby_people": "warn nearby people if needed",
    "preserve_interaction_space": "avoid cutting through the person-object activity space",
    "preserve_human_path": "avoid blocking where the person may move",
    "avoid_hazard_object": "stay clear of the object that may need attention",
    "avoid_hazard_event": "stay clear of the activity area",
    "increase human safety margin": "keep extra safety space around the person",
    "approach visibility continuity": "stay visible while approaching",
    "avoid near human": "avoid getting too close to people nearby",
    "notify nearby people": "warn nearby people if needed",
    "preserve interaction space": "avoid cutting through the person-object activity space",
    "preserve human path": "avoid blocking where the person may move",
    "avoid hazard object": "stay clear of the object that may need attention",
    "avoid hazard event": "stay clear of the activity area",
}


class Option(NamedTuple):
    label: str
    method: str
    image_path: Path | None = None
    title: str | None = None
    body: dict[str, Any] | None = None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def first_trial_dirs() -> list[Path]:
    scene_order = {"warehouse": 0, "office": 1, "hospital": 2}

    def sort_key(path: Path) -> tuple[int, str]:
        scene_name = path.name.split("_", 1)[0]
        return (scene_order.get(scene_name, 99), path.name)

    return sorted(
        (p for p in DATA_ROOT.iterdir() if p.is_dir() and (p / "manifest.json").exists()),
        key=sort_key,
    )


def get_query_value(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        return value[0] if value else default
    return str(value)


def selected_trial_dirs() -> list[Path]:
    trial_ids = get_query_value("trial_ids")
    if trial_ids:
        dirs = [DATA_ROOT / item.strip() for item in trial_ids.split(",") if item.strip()]
        return [d for d in dirs if d.is_dir() and (d / "manifest.json").exists()]
    return first_trial_dirs()


def trial_directory_label(index: int, trial_dir: Path) -> str:
    parts = trial_dir.name.split("_")
    if len(parts) >= 4:
        return f"{parts[2]}_{parts[0]}_{parts[3]}"
    return f"{index:03d}_{trial_dir.name}"


def event_id_for(index: int, trial_dir: Path) -> str:
    parts = trial_dir.name.split("_")
    if len(parts) >= 3:
        return parts[2]
    return f"{index:03d}"


def trial_anchor(index: int, trial_dir: Path) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in trial_directory_label(index, trial_dir).lower())
    return f"scene-{index:03d}-{safe}"


def rating_value(label: str | None) -> int | None:
    if not label:
        return None
    try:
        return int(label.split(" ", 1)[0])
    except (ValueError, IndexError):
        return None


def stable_shuffle(options: list[Option], *, participant_id: str, bundle_id: str, trial_dir: Path, section: str) -> list[Option]:
    if not RANDOMIZE_OPTION_ORDER:
        return options
    shuffled = list(options)
    seed_text = f"{participant_id}|{bundle_id}|{trial_dir.name}|{section}"
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    random.Random(seed).shuffle(shuffled)
    return shuffled


def option_display_order(options: list[Option]) -> dict[str, int]:
    return {option.label: index for index, option in enumerate(options, start=1)}


def display_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return DISPLAY_LABELS.get(text, text.replace("_", " "))


def important_text(value: Any, *, color: str = GREEN) -> str:
    text = html.escape(str(value or ""))
    return f"<span style='color:{color}; font-weight:700; font-style:italic;'>{text}</span>"


def caption_markdown(text: str) -> None:
    st.markdown(
        f"<div style='color:#9ca3af; font-size:0.88rem; text-align:center;'>{text}</div>",
        unsafe_allow_html=True,
    )


def important_auto(value: Any) -> str:
    return important_text(value, color=GREEN)


def score_text(value: Any) -> str:
    text = str(value or "")
    try:
        color = GREEN
    except ValueError:
        color = GREEN
    return important_text(f"{text} / 5", color=color)


def clean_participant_text(text: Any) -> str:
    raw = str(text or "").strip()
    replacements = {
        "Only the interaction label is used. The rule maps throwing to avoid.": (
            "Because the action looks like throwing, the robot would avoid the area."
        ),
        "The system selected warn because the DSG-grounded NeSy rule A1.Warn.HazardHumanAtRisk interprets the throwing event as a hazard/risk case for navigation. The supporting trace is trace_table_v0:A-1:warn_hazard_risk.": (
            "Because the person appears to be throwing a large object, the robot would warn nearby people and move carefully around the hazard."
        ),
        "No path-level social constraints are generated.": (
            "The robot uses a simple caution rule for moving near the person."
        ),
        "The selected constraints keep the robot visible and conservative around the human-object event. The goal policy is visible standoff with a preferred standoff distance of 1.2 m.": (
            "These precautions help the robot stay visible, keep a suitable buffer, and avoid the hazardous activity area."
        ),
        "This baseline uses only the interaction label. Its fixed mapping treats throwing as a case where the robot should route around the interaction instead of entering it; it does not use the scene graph, object geometry, human trajectory, or robot path context.": (
            "The person appears to be throwing an object, so the robot treats this as a situation where it should route around the activity."
        ),
        "This baseline uses only the interaction label. Its fixed rule treats throwing as a case where the robot should route around the interaction instead of entering it; it does not reason about the local scene graph, object geometry, human motion, or robot path.": (
            "The person appears to be throwing an object, so the robot treats this as a situation where it should route around the activity."
        ),
        "The constraints are generic social-navigation reminders from the fixed rule: keep a conservative distance. They are not grounded to the local map, the human's trajectory, or the human-object interaction geometry.": (
            "This gives the robot a simple safety buffer around the activity."
        ),
        "The constraints are generic reminders from the fixed rule; they are not grounded to the local map, human trajectory, or interaction space.": (
            "This gives the robot a simple safety buffer around the activity."
        ),
        "The proposed system selects warn because the DSG context indicates a potential hazard around the human-object event, so the robot should warn while staying socially visible. This combines the VLM interaction cue with DSG-grounded spatial and dynamic evidence. This decision is backed by the symbolic reasoning trace.": (
            "The person appears to be throwing a large object, which may create a local hazard. The robot should make itself visible and warn rather than simply pass through."
        ),
        "The selected constraints translate the reasoning result into navigation behavior: increase human safety margin, approach visibility continuity, avoid near human, notify nearby people, preserve interaction space, preserve human path, avoid hazard object, and avoid hazard event. Together they keep the robot's goal and path sensitive to the human, the object, the interaction space, and nearby social context. The goal policy is visible standoff, keeping about 1.2 m of standoff when possible.": (
            "This lets the robot respond to the hazard while reducing the chance of startling the person, blocking their movement, or entering the risky area."
        ),
    }
    if raw in replacements:
        return replacements[raw]
    return raw.replace("_", " ").replace("DSG", "scene").replace("VLM", "vision").replace("NeSy", "reasoning")


def task_plain_action(task: str) -> str:
    task = task.lower().strip()
    allowed = {"warn", "assist", "continue", "monitor", "avoid"}
    return task if task in allowed else display_value(task)


def summarize_constraints(nav_constraints: Any) -> str:
    if isinstance(nav_constraints, list):
        phrases = [display_value(item) for item in nav_constraints]
    else:
        phrases = [display_value(nav_constraints)]
    phrases = [p for p in phrases if p]
    if not phrases:
        return ""
    if len(phrases) <= 3:
        return "; ".join(phrases)
    keywords = ["safety", "visible", "activity space", "hazard", "blocking"]
    important = [p for p in phrases if any(k in p for k in keywords)]
    return "; ".join((important or phrases)[:4])


def option_c_plain_text(body: dict[str, Any]) -> dict[str, str]:
    task = display_value(body.get("selected_proactive_task", body.get("task", "")))
    return {
        "task": task_plain_action(task),
        "task_reason": clean_participant_text(body.get("task_reason", body.get("reasoning", ""))),
        "nav_constraints": summarize_constraints(body.get("selected_navigation_constraints", body.get("nav_constraints", ""))),
        "nav_reason": clean_participant_text(body.get("navigation_constraints_reason", body.get("path_constraints", ""))),
    }


def option_d_plain_text(body: dict[str, Any]) -> dict[str, str]:
    task = display_value(body.get("selected_proactive_task", body.get("task", "")))
    json_task_reason = clean_participant_text(body.get("task_reason", body.get("reasoning", "")))
    json_nav_constraints = summarize_constraints(body.get("selected_navigation_constraints", body.get("nav_constraints", "")))
    json_nav_reason = clean_participant_text(body.get("navigation_constraints_reason", body.get("path_constraints", "")))
    if json_task_reason or json_nav_constraints or json_nav_reason:
        return {
            "task": task_plain_action(task),
            "task_reason": json_task_reason,
            "nav_constraints": json_nav_constraints,
            "nav_reason": json_nav_reason,
        }

    templates = {
        "warn": {
            "task": "warn",
            "task_reason": "The person appears to be throwing a large object, which may create a local hazard. The robot should make itself visible and warn rather than simply pass through.",
            "nav_constraints": "keep a safe buffer, stay visible while approaching, avoid the person-object activity space, and stay clear of the hazardous object and activity area",
            "nav_reason": "This lets the robot respond to the hazard while reducing the chance of startling the person, blocking their movement, or entering the risky area.",
        },
        "assist": {
            "task": "assist",
            "task_reason": "The person may need help, and the robot can approach in a careful and socially appropriate way.",
            "nav_constraints": "approach from where the person can notice it, stop at a comfortable distance, and avoid cutting through the person-object activity space",
            "nav_reason": "This lets the robot offer help without surprising the person or getting in the way of what they are doing.",
        },
        "monitor": {
            "task": "monitor",
            "task_reason": "There may be a concern, but the scene does not clearly call for direct help, warning, or avoidance yet.",
            "nav_constraints": "keep the person and object in view from a safe distance without interrupting the activity",
            "nav_reason": "This lets the robot stay aware of the situation while avoiding unnecessary intervention.",
        },
        "avoid": {
            "task": "avoid",
            "task_reason": "The robot's route may interfere with the person or their activity, so it should keep clear.",
            "nav_constraints": "route around the activity space, avoid passing too close to people, and avoid blocking where the person may move",
            "nav_reason": "This helps the robot keep moving while respecting the person's space and activity.",
        },
        "continue": {
            "task": "continue",
            "task_reason": "There is no clear need for the robot to intervene, so it should continue its original task.",
            "nav_constraints": "keep polite space around people and avoid interrupting the person-object activity space",
            "nav_reason": "This lets the robot move normally while still behaving carefully around people.",
        },
    }
    return templates.get(task, {
        "task": task_plain_action(task),
        "task_reason": json_task_reason,
        "nav_constraints": json_nav_constraints,
        "nav_reason": json_nav_reason,
    })


def movement_plan_sentence(nav_constraints: str, nav_reason: str) -> str:
    raw_action = str(nav_constraints or "").strip()
    raw_result = str(nav_reason or "").strip()
    if raw_action and not raw_result and (". " in raw_action or raw_action[:1].isupper()):
        return raw_action.rstrip(".") + "."

    action = raw_action.rstrip(".")
    result = raw_result.rstrip(".")
    action_rewrites = {
        "Avoid the area where the object is being thrown": "avoid the area where the object is being thrown",
        "Avoid the path where the human is throwing the object": "avoid the path where the person is throwing the object",
        "Navigate away from the throwing object": "move away from the thrown object",
    }
    result_rewrites = {
        "Navigate away from the throwing object": "it stays away from the thrown object",
        "Avoid the path where the human is throwing the object": "it stays out of the object's path",
        "This gives the robot a simple safety buffer around the activity": "it keeps a simple safety buffer around the activity",
        "This lets the robot respond to the hazard while reducing the chance of startling the person, blocking their movement, or entering the risky area": "it can respond to the hazard without startling the person, blocking their movement, or entering the risky area",
        "This lets the robot offer help without surprising the person or getting in the way of what they are doing": "it can offer help without surprising the person or getting in the way",
        "This lets the robot stay aware of the situation while avoiding unnecessary intervention": "it can stay aware of the situation without unnecessary intervention",
        "This helps the robot keep moving while respecting the person's space and activity": "it can keep moving while respecting the person's space and activity",
        "This lets the robot move normally while still behaving carefully around people": "it can move normally while still behaving carefully around people",
    }
    action = action_rewrites.get(action, action[:1].lower() + action[1:] if action else "move carefully")
    result = result_rewrites.get(result, result[:1].lower() + result[1:] if result else "it can move appropriately around the scene")
    return f"The robot should {action} so that {result}."


def abs_if_exists(trial_dir: Path, filename: str) -> Path | None:
    path = trial_dir / filename
    return path if path.exists() else None


def is_warehouse_trial(trial_dir: Path) -> bool:
    return trial_dir.name.startswith("warehouse")


def show_image(
    path: Path | None,
    caption: str,
    *,
    width: int | None = None,
    rotate_ccw: bool = False,
) -> None:
    if path and path.exists():
        image: str | Image.Image
        if rotate_ccw:
            image = Image.open(path).rotate(90, expand=True)
        else:
            image = str(path)
        if width is None:
            st.image(image, caption=caption, width="stretch")
        else:
            st.image(image, caption=caption, width=width)
    else:
        st.warning(f"Missing image: {caption}")


def show_rgb_bev_pair(
    trial_dir: Path,
    rgb_path: Path | None,
    bev_path: Path | None,
    caption: str,
    *,
    rgb_caption: str | None = None,
    bev_caption: str | None = None,
    rgb_caption_markdown: str | None = None,
    bev_caption_markdown: str | None = None,
) -> None:
    with st.container(border=True):
        st.markdown(f"**{caption}**")
        left, right = st.columns([1.35, 1])
        with left:
            show_image(
                rgb_path,
                "" if rgb_caption_markdown else (rgb_caption or f"{caption}: RGB overlay"),
            )
            if rgb_caption_markdown:
                caption_markdown(rgb_caption_markdown)
        with right:
            show_image(
                bev_path,
                "" if bev_caption_markdown else (bev_caption or f"{caption}: map view"),
                rotate_ccw=is_warehouse_trial(trial_dir),
            )
            if bev_caption_markdown:
                caption_markdown(bev_caption_markdown)


def option_rating_grid(
    key_prefix: str,
    question: str,
    options: list[Option],
    scale: list[str],
    *,
    include_images: bool = False,
    question_inside_card: bool = False,
    card_label: str = "Option",
    show_rating_label: bool = True,
) -> dict[str, str]:
    if not question_inside_card:
        st.markdown(f"**{question}**")
    answers: dict[str, str] = {}
    for option in options:
        with st.container(border=True):
            st.markdown(f"**{card_label} {option.label}**")
            if question_inside_card:
                st.markdown(f"**{question}**")
            if include_images and option.image_path is not None:
                show_image(option.image_path, f"{card_label} {option.label}")
            answers[option.label] = st.radio(
                "Rating",
                scale,
                index=None,
                key=f"{key_prefix}_{option.label}",
                horizontal=True,
                label_visibility="visible" if show_rating_label else "collapsed",
            )
    return answers


def ranking_control(
    key_prefix: str,
    question: str,
    options: list[Option],
    *,
    card_label: str = "Robot",
    hint: str | None = None,
    question_markdown: str | None = None,
) -> dict[str, str]:
    if question_markdown:
        st.markdown(question_markdown, unsafe_allow_html=True)
    else:
        st.markdown(f"**{question}**")
    if hint:
        st.write(hint)
    labels = [option.label for option in options]
    selected: list[str] = []
    rank_names = [
        "1st / best",
        "2nd",
        "3rd",
        "4th",
        "5th",
    ]
    cols = st.columns(len(options))
    for index, col in enumerate(cols):
        with col:
            available = [label for label in labels if label not in selected]
            choice = st.selectbox(
                rank_names[index],
                ["Select..."] + [f"{card_label} {label}" for label in available],
                index=0,
                key=f"{key_prefix}_rank_{index + 1}",
            )
            if choice != "Select...":
                selected.append(choice.rsplit(" ", 1)[-1])
    rank_by_label = {label: "" for label in labels}
    for rank, label in enumerate(selected, start=1):
        rank_by_label[label] = f"{rank} {rank_names[rank - 1]}"
    return rank_by_label


def render_robot_summary_grid(
    options: list[Option],
    option_bodies: dict[str, dict[str, str]],
) -> None:
    cards = []
    for option in options:
        body = option_bodies[option.label]
        action = html.escape(body["task"])
        action_reason = html.escape(body["task_reason"])
        movement = html.escape(movement_plan_sentence(body["nav_constraints"], body["nav_reason"]))
        cards.append(
            f"""
<section class="robot-summary-card">
  <h4>Robot {option.label}</h4>
  <p><strong>Action:</strong> <strong class="robot-action">{action}</strong></p>
  <p><strong>Why this action:</strong> {action_reason}</p>
  <p><strong>Movement Plan:</strong> {movement}</p>
</section>
"""
        )
    st.markdown(
        f"""
<style>
.robot-summary-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin: 18px 0 28px;
}}
.robot-summary-card {{
  min-height: 260px;
  padding: 20px 22px;
  border: 1px solid rgba(128, 132, 149, 0.42);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.025);
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.robot-summary-card h4 {{
  margin: 0 0 4px;
  font-size: 1.05rem;
  font-weight: 750;
}}
.robot-summary-card p {{
  margin: 0;
  line-height: 1.52;
}}
.robot-summary-card .robot-action {{
  color: {RED};
  font-style: italic;
}}
@media (max-width: 900px) {{
  .robot-summary-grid {{
    grid-template-columns: 1fr;
  }}
  .robot-summary-card {{
    min-height: auto;
  }}
}}
</style>
<div class="robot-summary-grid">
{''.join(cards)}
</div>
""",
        unsafe_allow_html=True,
    )


def render_intro_page(scene_count: int) -> str | None:
    st.title("Robot Reasoning of Proactive Task and Navigation Decision")
    st.header("Background")
    with st.container(border=True):
        st.write("Imagine seeing everyday human activities through a robot's eyes.")
        st.write(
            "The robot is moving through everyday places such as workplaces, public buildings, "
            "storage areas, homes, or other shared indoor spaces. Around it, people are doing "
            "ordinary things: carrying boxes, pushing carts, reaching for items, placing objects "
            "down, or moving through a busy space."
        )
        st.write(
            "A robot in this kind of space should not only follow a route. It also needs to notice "
            "nearby people and objects, understand what may be happening, and choose a response that "
            "fits the situation. For example, it may need to continue normally, keep watching, avoid "
            "getting in the way, offer help, or warn someone about a possible risk."
        )
    with st.container(border=True):
        st.write(
            "This study evaluates robot reasoning and navigation decisions in short simulated scenes. "
            "You will not be asked to teach the robot or create rules for it. Instead, you will review "
            "what the robot says, what it chooses to do, and where it plans to move, then rate whether "
            "those outputs look reasonable for the scene."
        )
        st.write("For each scene, you will see:")
        st.markdown(
            """
1. Images showing the overall situation and the highlighted person-object interaction.
2. Short text descriptions of what the robot thinks may be happening.
3. Possible robot actions, reasons, target places, and routes.
4. Rating and ranking questions about the robot's reasoning and navigation choices.
"""
        )
        st.write(
            "There are no right or wrong answers. Some scenes may be unclear or ambiguous. "
            "Please use your best judgement based only on the information shown in the study."
        )
    with st.container(border=True):
        st.write("When answering the study questions, you will see these main robot response options:")
        st.markdown(
            """
- **Continue:** keep going as planned; no special response is needed.
- **Monitor:** keep observing because the situation may become relevant, but do not act yet.
- **Avoid:** adjust its path or behaviour to avoid getting in the way.
- **Assist:** offer or provide help if help seems useful.
- **Warn:** alert someone if there may be a risk, problem, or safety concern.
"""
        )
    st.header("Information Sheet and Consent")
    st.markdown(
        "Please read the consent form before continuing: "
        "[Study information and consent form]"
        "(https://docs.google.com/document/d/1jsRn9sQa50qqm864d-WQDgPj4AlHzSWwb_pth9uFji4/edit?usp=sharing)"
    )
    st.write("By selecting Yes, you confirm that:")
    st.markdown(
        """
- You have read and understood the study information.
- You voluntarily agree to participate.
- You understand that you may stop participating at any time.
- You agree that your survey responses will be stored securely and used only for research purposes.
"""
    )
    st.write(
        "If you do not agree to participate, select No and you will be directed to the exit page."
    )
    consent = st.radio(
        "Do you consent to participate?",
        ["Yes, I consent and wish to continue.", "No, I do not consent."],
        index=None,
        key="consent_choice",
    )
    if consent == "No, I do not consent.":
        st.header("Exit Page")
        st.write(
            "Thank you for your time. You have chosen not to participate, so the questionnaire will stop here."
        )
        return "no"
    if consent != "Yes, I consent and wish to continue.":
        st.write("Please select Yes if you consent and wish to continue.")
        return None

    st.header("Attitude Toward Robots")
    attitude = st.radio(
        "Which statement best describes your attitude toward robots or autonomous technologies in everyday environments?",
        [
            "A. I am very interested in them and generally positive.",
            "B. I am somewhat interested or open-minded.",
            "C. I am neutral.",
            "D. I am cautious but willing to evaluate them fairly.",
            "E. I strongly dislike them and would prefer not to engage with this topic.",
        ],
        index=None,
        key="robot_attitude",
    )
    if attitude == "E. I strongly dislike them and would prefer not to engage with this topic.":
        st.header("Exit Page")
        st.write(
            "Thank you for your time. Based on your response, the questionnaire will stop here."
        )
        return "no"
    if attitude is None:
        st.write("Please answer this question before continuing.")
        return None
    return "yes"


def render_scene_directory(trial_dirs: list[Path]) -> None:
    items = []
    for index, _trial_dir in enumerate(trial_dirs, start=1):
        label = str(index)
        target = html.escape(f"?scene_index={index - 1}")
        items.append(f"<a href='{target}'>{label}</a>")
    st.subheader("Scene Directory")
    st.write("Choose one scene to review. Each scene opens as its own page.")
    st.markdown(
        f"""
<style>
.scene-directory {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(56px, 1fr));
  gap: 8px 12px;
  margin: 10px 0 28px;
}}
.scene-directory a {{
  text-decoration: none;
  text-align: center;
  font-weight: 700;
  padding: 8px 10px;
  border: 1px solid rgba(128, 132, 149, 0.36);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.025);
}}
</style>
<div class="scene-directory">
{''.join(items)}
</div>
""",
        unsafe_allow_html=True,
    )


def option_prompt_rating_list(
    key_prefix: str,
    question: str,
    options: list[Option],
    scale: list[str],
    prompt_for_option: dict[str, str],
) -> dict[str, str]:
    st.markdown(f"**{question}**")
    answers: dict[str, str] = {}
    for option in options:
        with st.container(border=True):
            st.markdown(prompt_for_option.get(option.label, f"**Option {option.label}**"))
            answers[option.label] = st.radio(
                "Your rating",
                scale,
                index=None,
                key=f"{key_prefix}_{option.label}",
                horizontal=True,
            )
    return answers


def response_rows(
    *,
    participant_id: str,
    bundle_id: str,
    trial_dir: Path,
    task_label: str,
    question_id: str,
    question_text: str,
    answers: dict[str, str],
    option_methods: dict[str, str] | None = None,
    display_order: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for option_label, answer_label in answers.items():
        rows.append(
            {
                "timestamp_utc": now,
                "participant_id": participant_id,
                "bundle_id": bundle_id,
                "trial_id": trial_dir.name,
                "task_label": task_label,
                "question_id": question_id,
                "question_text": question_text,
                "option_label": option_label,
                "method": (option_methods or {}).get(option_label, ""),
                "display_order": (display_order or {}).get(option_label),
                "rating": rating_value(answer_label),
                "rating_label": answer_label or "",
            }
        )
    return rows


def secrets_section(name: str) -> dict[str, Any]:
    try:
        section = st.secrets.get(name, {})
    except Exception:
        return {}
    return dict(section) if section else {}


def append_rows_to_google_sheet(rows: list[dict[str, Any]]) -> str | None:
    responses_config = secrets_section("responses")
    spreadsheet_id = responses_config.get("spreadsheet_id") or responses_config.get("sheet_id")
    if not spreadsheet_id:
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise RuntimeError(
            "Google Sheets saving is configured, but gspread/google-auth is not installed."
        ) from exc

    service_account_info = secrets_section("gcp_service_account")
    if not service_account_info:
        service_account_info = secrets_section("gsheets_service_account")
    if not service_account_info:
        raise RuntimeError(
            "Google Sheets saving is configured, but no service account was found in Streamlit secrets."
        )

    if "private_key" in service_account_info:
        service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")

    worksheet_name = responses_config.get("worksheet", "responses")
    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=GOOGLE_SHEETS_SCOPES,
    )
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(str(spreadsheet_id))
    try:
        worksheet = spreadsheet.worksheet(str(worksheet_name))
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=str(worksheet_name), rows=1000, cols=32)

    fieldnames = list(rows[0].keys())
    existing_values = worksheet.get_all_values()
    header = existing_values[0] if existing_values else []
    if not header:
        worksheet.append_row(fieldnames)
        header = fieldnames
    else:
        merged_header = list(header)
        for name in fieldnames:
            if name not in merged_header:
                merged_header.append(name)
        if merged_header != header:
            worksheet.update("1:1", [merged_header])
            header = merged_header

    values = [[str(row.get(column, "")) for column in header] for row in rows]
    worksheet.append_rows(values, value_input_option="USER_ENTERED")
    return f"Google Sheet worksheet '{worksheet_name}'"


def append_rows_to_supabase(rows: list[dict[str, Any]]) -> str | None:
    supabase_config = secrets_section("supabase")
    supabase_url = str(supabase_config.get("url", "")).rstrip("/")
    supabase_key = supabase_config.get("key") or supabase_config.get("service_role_key") or supabase_config.get("anon_key")
    if not supabase_url or not supabase_key:
        return None

    table_name = supabase_config.get("table", DEFAULT_SUPABASE_TABLE)
    endpoint = f"{supabase_url}/rest/v1/{table_name}"
    payload = json.dumps(rows).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "apikey": str(supabase_key),
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 400:
                raise RuntimeError(f"Supabase returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase insert failed: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Supabase insert failed: {exc.reason}") from exc
    return f"Supabase table '{table_name}'"


def append_rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no rows"
    RESPONSE_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    exists = RESPONSE_CSV.exists()
    existing_rows: list[dict[str, str]] = []
    if exists:
        with RESPONSE_CSV.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_fieldnames = reader.fieldnames or []
            existing_rows = list(reader)
        merged = list(old_fieldnames)
        for name in fieldnames:
            if name not in merged:
                merged.append(name)
        if merged != old_fieldnames:
            with RESPONSE_CSV.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=merged)
                writer.writeheader()
                writer.writerows(existing_rows)
            fieldnames = merged
        else:
            fieldnames = old_fieldnames
    with RESPONSE_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)
    return str(RESPONSE_CSV)


def append_rows(rows: list[dict[str, Any]]) -> str:
    saved_to = append_rows_to_supabase(rows)
    if saved_to:
        return saved_to
    saved_to = append_rows_to_google_sheet(rows)
    if saved_to:
        return saved_to
    return append_rows_to_csv(rows)


def task_label_for(trial_dir: Path) -> str:
    manifest = read_json(trial_dir / "manifest.json")
    return str(manifest.get("task") or trial_dir.name.split("_")[3] if "_" in trial_dir.name else "")


def render_study_2a(trial_dir: Path, participant_id: str, bundle_id: str, task_label: str) -> list[dict[str, Any]]:
    st.header("Q1: Which Person and Object Matter?")
    st.write(
        "The robot sees several people and objects in the scene. "
        "Each option highlights one person and one object. "
        "Please rate whether the highlighted person and object seem to belong together in the scene, "
        "and whether they are important for the robot to notice."
    )
    show_image(abs_if_exists(trial_dir, "study_2a_stimulus_raw_rgb_plus_three_pair_crops_refined.png"), "Scene and options")

    options = [
        Option("A", "study2a_option_a"),
        Option("B", "study2a_option_b"),
        Option("C", "study2a_option_c"),
    ]
    answers = option_rating_grid(
        f"{trial_dir.name}_q1_pair_quality",
        "How reasonable is each highlighted person-object pair?",
        options,
        LIKERT_REASONABLE,
        show_rating_label=False,
    )
    return response_rows(
        participant_id=participant_id,
        bundle_id=bundle_id,
        trial_dir=trial_dir,
        task_label=task_label,
        question_id="Q1_pair_quality",
        question_text="How reasonable is each highlighted person-object pair?",
        answers=answers,
        option_methods={o.label: o.method for o in options},
    )


def render_study_1(trial_dir: Path, participant_id: str, bundle_id: str, task_label: str) -> list[dict[str, Any]]:
    st.header("Q2: Does the Robot Understand the Scene?")
    parsed = read_json(trial_dir / "study_1_proposed_hoir1_parsed_output.json")
    show_image(abs_if_exists(trial_dir, "study_1_proposed_hoir1_crop.png"), "Highlighted person and object", width=420)

    questions = [
        ("Q2_1_action", f"The robot says the person is doing: {important_auto(display_value(parsed.get('verb class')))}. How reasonable is this?", LIKERT_AGREE),
        ("Q2_2_person_state", f"The robot says the person's state is: {important_auto(display_value(parsed.get('human state')))}. How reasonable is this?", LIKERT_AGREE),
        ("Q2_3_object_state", f"The robot says the object's state is: {important_auto(display_value(parsed.get('object property')))}. How reasonable is this?", LIKERT_AGREE),
        ("Q2_4_help_needed", f"The robot gives the help-needed score as: {score_text(parsed.get('need level', ''))}. Do you agree with this score?", LIKERT_AGREE),
        ("Q2_5_attention_needed", f"The robot gives the attention-needed score as: {score_text(parsed.get('risk level', ''))}. Do you agree with this score?", LIKERT_AGREE),
        ("Q2_6_concern", f"The robot gives the concern score as: {score_text(parsed.get('hazard level', ''))}. Do you agree with this score?", LIKERT_AGREE),
        ("Q2_7_main_concern", f"The robot says the main thing to pay attention to is: {important_auto(display_value(parsed.get('risk type')))}. How reasonable is this?", LIKERT_AGREE),
        ("Q2_8_overall", "Overall, the robot understood this person-object situation well enough to decide what to do next.", LIKERT_AGREE),
    ]
    rows: list[dict[str, Any]] = []
    for qid, text, scale in questions:
        st.markdown(text, unsafe_allow_html=True)
        answer = st.radio(
            "Your rating",
            scale,
            index=None,
            key=f"{trial_dir.name}_{qid}",
            label_visibility="collapsed",
            horizontal=True,
        )
        rows.extend(
            response_rows(
                participant_id=participant_id,
                bundle_id=bundle_id,
                trial_dir=trial_dir,
                task_label=task_label,
                question_id=qid,
                question_text=text,
                answers={"robot_output": answer},
                option_methods={"robot_output": "hoir1"},
            )
        )
    return rows


def render_method_card(option: str, body: dict[str, Any]) -> None:
    st.markdown(f"**Option {option}**")
    st.markdown(
        f"""
**What the robot would do:**  
{body.get("selected_proactive_task", body.get("task", ""))}

**Why:**  
{body.get("task_reason", body.get("reasoning", ""))}

**What the robot should be careful about while moving:**  
{body.get("selected_navigation_constraints", body.get("nav_constraints", ""))}

**Why this matters:**  
{body.get("navigation_constraints_reason", body.get("path_constraints", ""))}
"""
    )


def study_2b_body(summary: dict[str, Any], method: str) -> dict[str, str]:
    body = summary.get(method, {})
    if method == "b3_rule_based":
        return option_c_plain_text(body)
    if method == "proposed_vlm_dsg_nesy":
        return option_d_plain_text(body)
    task = display_value(body.get("selected_proactive_task", body.get("task", "")))
    task_reason = clean_participant_text(body.get("task_reason", body.get("reasoning", "")))
    nav_constraints = body.get("selected_navigation_constraints", body.get("nav_constraints", ""))
    nav_constraints_text = summarize_constraints(nav_constraints)
    nav_reason = clean_participant_text(body.get("navigation_constraints_reason", body.get("path_constraints", "")))
    return {
        "task": task,
        "task_reason": task_reason,
        "nav_constraints": nav_constraints_text,
        "nav_reason": nav_reason,
    }


def study_2b_q3b_body(summary: dict[str, Any], method: str) -> dict[str, str]:
    body = summary.get(method, {})
    if any(key in body for key in ("q3b_task_reason", "q3b_movement_plan")):
        return {
            "task": task_plain_action(display_value(body.get("q3b_selected_proactive_task", body.get("selected_proactive_task", "")))),
            "task_reason": clean_participant_text(body.get("q3b_task_reason", "")),
            "nav_constraints": clean_participant_text(body.get("q3b_movement_plan", "")),
            "nav_reason": "",
        }
    return study_2b_body(summary, method)


def add_rating_row(
    rows: list[dict[str, Any]],
    *,
    participant_id: str,
    bundle_id: str,
    trial_dir: Path,
    task_label: str,
    question_id: str,
    question_text: str,
    option: Option,
    answer: str | None,
    display_order: dict[str, int] | None = None,
) -> None:
    rows.extend(
        response_rows(
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id=question_id,
            question_text=question_text,
            answers={option.label: answer or ""},
            option_methods={option.label: option.method},
            display_order=display_order,
        )
    )


def add_score_question(
    rows: list[dict[str, Any]],
    *,
    participant_id: str,
    bundle_id: str,
    trial_dir: Path,
    task_label: str,
    question_id: str,
    question_text: str,
    option: Option,
    display_order: dict[str, int],
) -> None:
    answer = st.radio(
        question_text,
        SCORE_1_TO_10,
        index=None,
        key=f"{trial_dir.name}_{question_id}_{option.label}",
        horizontal=True,
    )
    add_rating_row(
        rows,
        participant_id=participant_id,
        bundle_id=bundle_id,
        trial_dir=trial_dir,
        task_label=task_label,
        question_id=question_id,
        question_text=question_text,
        option=option,
        answer=answer,
        display_order=display_order,
    )


def render_study_2b(trial_dir: Path, participant_id: str, bundle_id: str, task_label: str) -> list[dict[str, Any]]:
    st.header("Q3: Robot Decision")
    show_image(abs_if_exists(trial_dir, "study_1_proposed_full_rgb.png"), "Full scene")
    st.write(
        "Each robot gives one possible response for the same scene. "
        "First, judge whether the robot reacts at the right level and chooses a good action."
    )
    summary = read_json(trial_dir / "study_2b_text_summary_refined.json").get("conditions", {})
    method_order = [
        ("A", "b1_vlm_without_dsg"),
        ("B", "b2_vlm_with_dsg_neural_only"),
        ("C", "b3_rule_based"),
        ("D", "proposed_vlm_dsg_nesy"),
    ]
    options = [Option(label, method) for label, method in method_order]
    display_options = stable_shuffle(
        options,
        participant_id=participant_id,
        bundle_id=bundle_id,
        trial_dir=trial_dir,
        section="Q3",
    )
    display_order = option_display_order(display_options)
    rows: list[dict[str, Any]] = []
    option_bodies = {
        label: study_2b_body(summary, method)
        for label, method in method_order
    }

    selected_task_options: list[Option] = []
    seen_tasks: set[str] = set()
    for option in display_options:
        task = str(option_bodies[option.label]["task"])
        if task not in seen_tasks:
            selected_task_options.append(Option(task, f"selected_task:{task}"))
            seen_tasks.add(task)
    task_display_order = option_display_order(selected_task_options)

    st.subheader("Q3A: Which Selected Task Makes the Best Decision?")
    st.write(
        "First, look at all robot tasks selected for this scene. If several robots chose the same task, "
        "that task appears only once here. Judge each selected task by itself."
    )
    for row_start in range(0, len(selected_task_options), 2):
        cols = st.columns(2, vertical_alignment="top")
        for col, option in zip(cols, selected_task_options[row_start:row_start + 2]):
            with col:
                with st.container(border=True):
                    st.subheader(f"Selected task: {option.label}")
                    st.markdown(
                        f"**Robot task:** {important_text(option.label, color=RED)}",
                        unsafe_allow_html=True,
                    )
                    reaction_question = (
                        "How appropriate is the robot's reaction level for this scene? "
                        "Use underreacts if the robot should do more, and overreacts if the robot does too much."
                    )
                    reaction_answer = st.radio(
                        reaction_question,
                        LIKERT_UNDER_OVER_REACT,
                        index=None,
                        key=f"{trial_dir.name}_Q3A_1_reaction_level_task_{option.label}",
                        horizontal=True,
                    )
                    add_rating_row(
                        rows,
                        participant_id=participant_id,
                        bundle_id=bundle_id,
                        trial_dir=trial_dir,
                        task_label=task_label,
                        question_id="Q3A_1_reaction_level",
                        question_text=reaction_question,
                        option=option,
                        answer=reaction_answer,
                        display_order=task_display_order,
                    )
                    add_score_question(
                        rows,
                        participant_id=participant_id,
                        bundle_id=bundle_id,
                        trial_dir=trial_dir,
                        task_label=task_label,
                        question_id="Q3A_2_action_decision_quality",
                        question_text="How good is this selected task for this scene? 1 means very poor, and 10 means excellent.",
                        option=option,
                        display_order=task_display_order,
                    )

    decision_ranking_answers = ranking_control(
        f"{trial_dir.name}_Q3A_0_selected_task_quality_rank",
        "Rank all selected tasks by overall decision quality.",
        selected_task_options,
        card_label="Task",
        hint="Choose each selected task once. Rank 1 means the best task decision for this scene.",
    )
    rows.extend(
        response_rows(
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id="Q3A_0_selected_task_quality_rank",
            question_text="Rank all selected tasks by overall decision quality.",
            answers=decision_ranking_answers,
            option_methods={o.label: o.method for o in selected_task_options},
            display_order=task_display_order,
        )
    )

    st.divider()
    st.header("Q4A: High-Level Natural Language Planning")
    show_image(abs_if_exists(trial_dir, "study_1_proposed_full_rgb.png"), "Full scene")
    proposed_body = option_bodies["D"]
    st.markdown(
        f"""
Now all robots use the same robot decision and describe why this decision makes sense and how the robot should move.

**Robot action:** {important_text(proposed_body['task'], color=RED)}

Please judge the explanation quality and whether the movement plan supports the robot's task.
""",
        unsafe_allow_html=True,
    )
    for row_start in range(0, len(display_options), 2):
        cols = st.columns(2, vertical_alignment="top")
        for col, option in zip(cols, display_options[row_start:row_start + 2]):
            body = study_2b_q3b_body(summary, option.method)
            with col:
                with st.container(border=True):
                    st.subheader(f"Robot {option.label}")
                    st.markdown(
                        f"""
**Robot action:** {important_text(proposed_body['task'], color=RED)}

**Explanation:** {html.escape(body['task_reason'])}

**Movement Plan:** {html.escape(movement_plan_sentence(body['nav_constraints'], body['nav_reason']))}
""",
                        unsafe_allow_html=True,
                    )
                    add_score_question(
                        rows,
                        participant_id=participant_id,
                        bundle_id=bundle_id,
                        trial_dir=trial_dir,
                        task_label=task_label,
                        question_id="Q4A_1_task_movement_plan_match",
                        question_text="How well does this movement plan support the robot's task? 1 means not well at all, and 10 means extremely well.",
                        option=option,
                        display_order=display_order,
                    )
                    add_score_question(
                        rows,
                        participant_id=participant_id,
                        bundle_id=bundle_id,
                        trial_dir=trial_dir,
                        task_label=task_label,
                        question_id="Q4A_2_explanation_clarity",
                        question_text="How clear is this explanation? 1 means not clear at all, and 10 means extremely clear.",
                        option=option,
                        display_order=display_order,
                    )
                    add_score_question(
                        rows,
                        participant_id=participant_id,
                        bundle_id=bundle_id,
                        trial_dir=trial_dir,
                        task_label=task_label,
                        question_id="Q4A_3_scene_information_use",
                        question_text="How well does this explanation use the scene information? 1 means not well at all, and 10 means extremely well.",
                        option=option,
                        display_order=display_order,
                    )
                    add_score_question(
                        rows,
                        participant_id=participant_id,
                        bundle_id=bundle_id,
                        trial_dir=trial_dir,
                        task_label=task_label,
                        question_id="Q4A_4_trust",
                        question_text="Based on this explanation, how much would you trust this robot's reasoning? 1 means not at all, and 10 means completely.",
                        option=option,
                        display_order=display_order,
                    )

    movement_ranking_answers = ranking_control(
        f"{trial_dir.name}_Q4A_0_task_movement_plan_match_rank",
        "Rank the four robots by task-movement plan matching quality.",
        display_options,
        card_label="Robot",
        hint="Choose each robot once. Rank 1 means the best task-movement plan match for this scene.",
    )
    rows.extend(
        response_rows(
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id="Q4A_0_task_movement_plan_match_rank",
            question_text="Rank the four robots by task-movement plan matching quality.",
            answers=movement_ranking_answers,
            option_methods={o.label: o.method for o in options},
            display_order=display_order,
        )
    )
    explanation_ranking_answers = ranking_control(
        f"{trial_dir.name}_Q4A_0_explanation_quality_rank",
        "Rank the four robots by explanation quality.",
        display_options,
        card_label="Robot",
        hint="Choose each robot once. Rank 1 means the best explanation quality for this scene.",
    )
    rows.extend(
        response_rows(
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id="Q4A_0_explanation_quality_rank",
            question_text="Rank the four robots by explanation quality.",
            answers=explanation_ranking_answers,
            option_methods={o.label: o.method for o in options},
            display_order=display_order,
        )
    )
    return rows


def render_study_3b(trial_dir: Path, participant_id: str, bundle_id: str, task_label: str) -> list[dict[str, Any]]:
    st.header("Q4B: Low-Level Updated Goal and Route")
    task_gloss = {
        "warn": "warn or alert people",
        "assist": "help the person",
        "monitor": "monitor (observe the situation)",
        "avoid": "avoid the area",
        "continue": "continue normally",
    }
    task_text = task_gloss.get(task_label, task_label)
    task_html = important_text(task_text, color=RED)
    st.markdown(
        f"""
The robot's task in this scene is to {task_html}.

The grey goal-path shows where the robot originally planned to go and how it originally planned to get there.
Each robot shows a changed target place and route. Please evaluate each update from two perspectives:
whether it supports the robot's task, and whether the target place and route follow normal social expectations
around people.
""",
        unsafe_allow_html=True,
    )

    options = [
        Option("A", "rule_nearest_goal"),
        Option("B", "vlm_dsg_neural_goal_pose"),
        Option("C", "proposed_nesy_dsg_goal_pose"),
    ]
    display_options = stable_shuffle(
        options,
        participant_id=participant_id,
        bundle_id=bundle_id,
        trial_dir=trial_dir,
        section="Q4B",
    )
    display_order = option_display_order(display_options)
    visuals = {
        "A": (
            abs_if_exists(trial_dir, "study_3b_option_a_rgb_traj.png"),
            abs_if_exists(trial_dir, "study_3b_option_a_bev.png"),
        ),
        "B": (
            abs_if_exists(trial_dir, "study_3b_option_b_rgb_traj.png"),
            abs_if_exists(trial_dir, "study_3b_option_b_bev.png"),
        ),
        "C": (
            abs_if_exists(trial_dir, "study_3b_option_c_rgb_traj.png"),
            abs_if_exists(trial_dir, "study_3b_option_c_bev.png"),
        ),
    }
    rows: list[dict[str, Any]] = []
    for option in display_options:
        st.subheader(f"Robot {option.label}")
        rgb_path, bev_path = visuals[option.label]
        route_color = ROBOT_ROUTE_COLORS.get(option.label, "colored")
        show_rgb_bev_pair(
            trial_dir,
            rgb_path,
            bev_path,
            f"Robot {option.label}",
            rgb_caption_markdown=(
                f"Robot {option.label}: RGB view. This is what the robot sees from the red start position. "
                "The grey goal-path is where the robot originally planned to go. "
                f"After seeing this scene, the robot decides to {task_html} and updates its navigation "
                f"decision to the {html.escape(route_color)} path."
            ),
            bev_caption_markdown=(
                f"Robot {option.label}: map view. The red point and arrow show the robot's current position "
                "and facing direction. Blue points and arrows show people and how they are moving. "
                f"The grey path is the robot's original plan; the {html.escape(route_color)} path is Robot "
                f"{option.label}'s updated navigation decision."
            ),
        )

        support_question = f"How well does this updated goal and route support the robot's task: {task_text}?"
        st.markdown(
            f"**How well does this updated goal and route support the robot's task: {task_html}?**",
            unsafe_allow_html=True,
        )
        support_answer = st.radio(
            "Task support rating",
            LIKERT_POOR_WELL,
            index=None,
            key=f"{trial_dir.name}_Q4B_1_task_support_{option.label}",
            horizontal=True,
            label_visibility="collapsed",
        )
        add_rating_row(
            rows,
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id="Q4B_1_task_support",
            question_text=support_question,
            option=option,
            answer=support_answer,
            display_order=display_order,
        )

        goal_answer = st.radio(
            "How socially appropriate is the updated target place around the person?",
            LIKERT_INAPPROPRIATE_APPROPRIATE,
            index=None,
            key=f"{trial_dir.name}_Q4B_2_goal_appropriateness_{option.label}",
            horizontal=True,
        )
        add_rating_row(
            rows,
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id="Q4B_2_goal_appropriateness",
            question_text="How socially appropriate is the updated target place around the person?",
            option=option,
            answer=goal_answer,
            display_order=display_order,
        )

    st.subheader("Overall Ranking")
    show_rgb_bev_pair(
        trial_dir,
        abs_if_exists(trial_dir, "study_3b_goal_path_rgb_overlay_refined.png"),
        abs_if_exists(trial_dir, "study_3b_goal_path_reference_map_refined.png"),
        "All robots together",
        rgb_caption=(
            "All robots together: RGB view. The robot starts at the red marker and sees the scene on the left. "
            "The grey goal-path is its original plan. The orange, cyan, and green paths show the updated "
            "navigation decisions from Robot A, Robot B, and Robot C."
        ),
        bev_caption=(
            "All robots together: map view. Red shows the robot's current position and facing direction. "
            "Blue points and arrows show people and how they are moving. Grey is the original plan; "
            "orange, cyan, and green are the updated navigation decisions from the three robots."
        ),
    )
    overall_answers = ranking_control(
        f"{trial_dir.name}_Q4B_3_overall_route_rank",
        f"Rank the three robots by overall updated goal and route quality for the task: {task_text}.",
        display_options,
        card_label="Robot",
        hint="Consider both task support and social appropriateness. Rank 1 means the best updated goal and route overall.",
        question_markdown=(
            f"**Rank the three robots by overall updated goal and route quality for the task: {task_html}.**"
        ),
    )
    rows.extend(
        response_rows(
            participant_id=participant_id,
            bundle_id=bundle_id,
            trial_dir=trial_dir,
            task_label=task_label,
            question_id="Q4B_3_overall_route_rank",
            question_text=f"Rank the three robots by overall updated goal and route quality for the task: {task_text}.",
            answers=overall_answers,
            option_methods={o.label: o.method for o in options},
            display_order=display_order,
        )
    )
    return rows


def render_trial(trial_dir: Path, participant_id: str, bundle_id: str) -> list[dict[str, Any]]:
    task_label = task_label_for(trial_dir)
    rows: list[dict[str, Any]] = []
    rows.extend(render_study_2a(trial_dir, participant_id, bundle_id, task_label))
    st.divider()
    rows.extend(render_study_1(trial_dir, participant_id, bundle_id, task_label))
    st.divider()
    rows.extend(render_study_2b(trial_dir, participant_id, bundle_id, task_label))
    st.divider()
    rows.extend(render_study_3b(trial_dir, participant_id, bundle_id, task_label))
    return rows


def sidebar_scene_choice(trial_dirs: list[Path]) -> int | None:
    query_index = get_query_value("scene_index")
    default_position = 0
    if query_index:
        try:
            parsed = int(query_index)
            if 0 <= parsed < len(trial_dirs):
                default_position = parsed + 1
        except ValueError:
            default_position = 0

    options: list[int | None] = [None] + list(range(len(trial_dirs)))

    def label(option: int | None) -> str:
        if option is None:
            return "Directory"
        return str(option + 1)

    st.sidebar.title("Event")
    st.sidebar.caption("Select one event to review.")
    return st.sidebar.selectbox(
        "Event",
        options,
        index=default_position,
        format_func=label,
        label_visibility="collapsed",
        key="sidebar_event_selector",
    )


def main() -> None:
    st.set_page_config(page_title="Robot Reasoning of Proactive Task and Navigation Decision", layout="wide")
    participant_id = get_query_value("participant_id", "anonymous_participant")
    bundle_id = get_query_value("bundle_id", "review_bundle")

    if not DATA_ROOT.exists():
        st.error(f"Data root does not exist: {DATA_ROOT}")
        return
    trial_dirs = selected_trial_dirs()
    if not trial_dirs:
        st.error("No trial directories found.")
        return

    selected_index = sidebar_scene_choice(trial_dirs)

    if selected_index is None:
        consent = render_intro_page(len(trial_dirs))
        if consent != "yes":
            return
        st.divider()
        render_scene_directory(trial_dirs)
        return

    index = selected_index + 1
    trial_dir = trial_dirs[selected_index]
    scene_anchor = trial_anchor(index, trial_dir)
    st.markdown(
        f"<h1 id='{scene_anchor}'>Scene {index}</h1>",
        unsafe_allow_html=True,
    )
    st.write(
        "Please review this scene carefully. Imagine this is what the robot sees as it moves "
        "through the environment. The robot needs to understand what is happening and decide "
        "what it should do next."
    )
    all_rows = render_trial(trial_dir, participant_id, bundle_id)

    st.divider()
    st.subheader("Submit")
    st.write("Please submit after answering all visible questions.")
    if st.button("Submit responses", type="primary"):
        missing = [r for r in all_rows if r["rating"] is None]
        if missing:
            st.error(f"Please answer all questions before submitting. Missing: {len(missing)} ratings.")
        else:
            saved_to = append_rows(all_rows)
            st.success(f"Saved {len(all_rows)} ratings to {saved_to}")


if __name__ == "__main__":
    main()
