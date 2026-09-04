from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "streamlit_user_study" / "assets"
OUTPUT_ROOT = REPO_ROOT / "participant_scene_assignments_3reviews_65p"
APP_URL = "https://robot-reasoning-proactive-task-navigation.streamlit.app/"

SCENE_ORDER = {"warehouse": 0, "office": 1, "hospital": 2}
PARTICIPANT_COUNT = 65
REVIEWS_PER_SCENE = 3


@dataclass(frozen=True)
class Scene:
    scene_number: int
    scene_dir: str
    environment: str
    event_id: str
    task: str
    object_label: str
    object_category: str
    scene_interactiveobj: str
    action: str
    url_anchor: str


def scene_sort_key(path: Path) -> tuple[int, str]:
    environment = path.name.split("_", 1)[0]
    return (SCENE_ORDER.get(environment, 99), path.name)


def strip_object_instance(object_label: str) -> str:
    parts = object_label.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return object_label


def parse_scene(path: Path, scene_number: int) -> Scene:
    parts = path.name.split("_")
    environment = parts[0]
    event_id = parts[2]
    task = parts[3]
    proposal_index = parts.index("proposal")
    object_label = "_".join(parts[4:proposal_index])
    object_category = strip_object_instance(object_label)
    action = path.name.split("_stamp_", 1)[1].split("_", 1)[1]
    return Scene(
        scene_number=scene_number,
        scene_dir=path.name,
        environment=environment,
        event_id=event_id,
        task=task,
        object_label=object_label,
        object_category=object_category,
        scene_interactiveobj=f"{environment}_{object_category}",
        action=action,
        url_anchor=f"#scene-{scene_number:03d}-{event_id}-{environment}-{task}",
    )


def load_scenes() -> list[Scene]:
    paths = sorted(
        [p for p in ASSET_ROOT.iterdir() if p.is_dir() and (p / "manifest.json").exists()],
        key=scene_sort_key,
    )
    return [parse_scene(path, index) for index, path in enumerate(paths, start=1)]


def participant_patterns() -> list[list[str]]:
    # 65 participants x 3 scenes = 195 slots.
    # Repeating all scenes 3 times gives W=48, O=117, H=30 slots.
    patterns = []
    patterns.extend([["warehouse", "office", "hospital"] for _ in range(13)])
    patterns.extend([["warehouse", "office", "office"] for _ in range(35)])
    patterns.extend([["hospital", "office", "office"] for _ in range(17)])
    return patterns


def duplicate_penalty(values: list[str], weight: int) -> int:
    counts = Counter(values)
    return sum((count - 1) * weight for count in counts.values() if count > 1)


def participant_cost(scenes: list[Scene]) -> int:
    cost = 0
    cost += duplicate_penalty([scene.scene_dir for scene in scenes], 10_000)
    cost += duplicate_penalty([scene.scene_interactiveobj for scene in scenes], 800)
    cost += duplicate_penalty([scene.task for scene in scenes], 300)
    cost += duplicate_penalty([scene.object_label for scene in scenes], 180)
    cost += duplicate_penalty([scene.object_category for scene in scenes], 80)
    cost += duplicate_penalty([f"{scene.environment}_{scene.event_id}" for scene in scenes], 150)
    cost += duplicate_penalty([scene.action for scene in scenes], 30)
    return cost


def assignment_cost(assignment: list[list[Scene]]) -> int:
    return sum(participant_cost(scenes) for scenes in assignment)


def make_initial_assignment(scenes: list[Scene], rng: random.Random) -> list[list[Scene]]:
    patterns = participant_patterns()
    slots_by_env: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for participant_index, pattern in enumerate(patterns):
        for slot_index, environment in enumerate(pattern):
            slots_by_env[environment].append((participant_index, slot_index))

    scene_copies_by_env: dict[str, list[Scene]] = defaultdict(list)
    for scene in scenes:
        scene_copies_by_env[scene.environment].extend([scene] * REVIEWS_PER_SCENE)

    assignment: list[list[Scene | None]] = [[None, None, None] for _ in range(PARTICIPANT_COUNT)]
    for environment, slots in slots_by_env.items():
        copies = scene_copies_by_env[environment]
        if len(copies) != len(slots):
            raise ValueError(f"Slot mismatch for {environment}: {len(slots)} slots, {len(copies)} scene copies")
        rng.shuffle(copies)
        rng.shuffle(slots)
        for (participant_index, slot_index), scene in zip(slots, copies):
            assignment[participant_index][slot_index] = scene

    return [[scene for scene in participant if scene is not None] for participant in assignment]


def optimise_assignment(scenes: list[Scene], seed: int) -> tuple[int, list[list[Scene]]]:
    rng = random.Random(seed)
    assignment = make_initial_assignment(scenes, rng)
    costs = [participant_cost(participant) for participant in assignment]
    total_cost = sum(costs)

    env_slots: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for participant_index, participant in enumerate(assignment):
        for slot_index, scene in enumerate(participant):
            env_slots[scene.environment].append((participant_index, slot_index))

    for _ in range(80_000):
        environment = rng.choice(list(env_slots))
        slot_a, slot_b = rng.sample(env_slots[environment], 2)
        pa, sa = slot_a
        pb, sb = slot_b
        if pa == pb:
            continue

        before = costs[pa] + costs[pb]
        assignment[pa][sa], assignment[pb][sb] = assignment[pb][sb], assignment[pa][sa]
        after_a = participant_cost(assignment[pa])
        after_b = participant_cost(assignment[pb])
        after = after_a + after_b

        if after <= before:
            total_cost += after - before
            costs[pa] = after_a
            costs[pb] = after_b
        else:
            assignment[pa][sa], assignment[pb][sb] = assignment[pb][sb], assignment[pa][sa]

    return total_cost, assignment


def best_assignment(scenes: list[Scene]) -> tuple[int, list[list[Scene]]]:
    best_cost = 10**18
    best: list[list[Scene]] | None = None
    for seed in range(250):
        cost, assignment = optimise_assignment(scenes, seed)
        if cost < best_cost:
            best_cost = cost
            best = assignment
            if best_cost == 0:
                break
    if best is None:
        raise RuntimeError("No assignment generated")
    return best_cost, best


def participant_id(index: int) -> str:
    return f"P{index:03d}"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_rows(assignment: list[list[Scene]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    long_rows: list[dict[str, object]] = []
    wide_rows: list[dict[str, object]] = []
    for participant_index, participant_scenes in enumerate(assignment, start=1):
        pid = participant_id(participant_index)
        wide_row: dict[str, object] = {"participant_id": pid}
        for slot, scene in enumerate(participant_scenes, start=1):
            row = {
                "participant_id": pid,
                "slot": slot,
                "scene_no": scene.scene_number,
                "event_id": scene.event_id,
                "task": scene.task,
                "environment": scene.environment,
                "object_label": scene.object_label,
                "object_category": scene.object_category,
                "scene_interactiveobj": scene.scene_interactiveobj,
                "action": scene.action,
                "scene_dir": scene.scene_dir,
                "asset_path": str(ASSET_ROOT / scene.scene_dir),
                "url_anchor": scene.url_anchor,
            }
            long_rows.append(row)
            prefix = f"scene_{slot}"
            wide_row[f"{prefix}_no"] = scene.scene_number
            wide_row[f"{prefix}_event_id"] = scene.event_id
            wide_row[f"{prefix}_task"] = scene.task
            wide_row[f"{prefix}_environment"] = scene.environment
            wide_row[f"{prefix}_object_label"] = scene.object_label
            wide_row[f"{prefix}_object_category"] = scene.object_category
            wide_row[f"{prefix}_dir"] = scene.scene_dir
            wide_row[f"{prefix}_url_anchor"] = scene.url_anchor
        # Keep scene_4/scene_5 columns empty so the current Streamlit loader can read the file safely.
        for slot in (4, 5):
            prefix = f"scene_{slot}"
            wide_row[f"{prefix}_no"] = ""
            wide_row[f"{prefix}_event_id"] = ""
            wide_row[f"{prefix}_task"] = ""
            wide_row[f"{prefix}_environment"] = ""
            wide_row[f"{prefix}_object_label"] = ""
            wide_row[f"{prefix}_object_category"] = ""
            wide_row[f"{prefix}_dir"] = ""
            wide_row[f"{prefix}_url_anchor"] = ""
        wide_rows.append(wide_row)
    return long_rows, wide_rows


def write_summaries(long_rows: list[dict[str, object]], cost: int) -> None:
    by_scene = Counter(row["scene_dir"] for row in long_rows)
    scene_summary = [
        {
            "scene_no": next(row["scene_no"] for row in long_rows if row["scene_dir"] == scene_dir),
            "scene_dir": scene_dir,
            "review_count": count,
        }
        for scene_dir, count in sorted(by_scene.items(), key=lambda item: int(next(row["scene_no"] for row in long_rows if row["scene_dir"] == item[0])))
    ]

    by_interactiveobj = Counter(row["scene_interactiveobj"] for row in long_rows)
    interactive_summary = [
        {"scene_interactiveobj": key, "assigned_count": count}
        for key, count in sorted(by_interactiveobj.items())
    ]

    participant_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in long_rows:
        participant_groups[str(row["participant_id"])].append(row)

    duplicate_object_category = 0
    duplicate_exact_object = 0
    duplicate_interactiveobj = 0
    duplicate_task = 0
    environment_patterns = Counter()
    for rows in participant_groups.values():
        duplicate_object_category += int(len({row["object_category"] for row in rows}) < len(rows))
        duplicate_exact_object += int(len({row["object_label"] for row in rows}) < len(rows))
        duplicate_interactiveobj += int(len({row["scene_interactiveobj"] for row in rows}) < len(rows))
        duplicate_task += int(len({row["task"] for row in rows}) < len(rows))
        environment_patterns["+".join(sorted(str(row["environment"]) for row in rows))] += 1

    report = [
        "3-review / 65-participant assignment validation",
        f"optimisation_cost: {cost}",
        f"participants: {len(participant_groups)}",
        f"rows: {len(long_rows)}",
        f"unique_scenes: {len(by_scene)}",
        f"scene_review_counts: {dict(sorted(Counter(by_scene.values()).items()))}",
        f"participant_scene_counts: {dict(sorted(Counter(len(rows) for rows in participant_groups.values()).items()))}",
        f"environment_slot_counts: {dict(sorted(Counter(row['environment'] for row in long_rows).items()))}",
        f"task_slot_counts: {dict(sorted(Counter(row['task'] for row in long_rows).items()))}",
        f"environment_patterns: {dict(sorted(environment_patterns.items()))}",
        f"participants_with_duplicate_task: {duplicate_task}",
        f"participants_with_duplicate_exact_object: {duplicate_exact_object}",
        f"participants_with_duplicate_object_category: {duplicate_object_category}",
        f"participants_with_duplicate_environment_object_category: {duplicate_interactiveobj}",
    ]
    (OUTPUT_ROOT / "validation_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    write_csv(
        OUTPUT_ROOT / "scene_assignment_summary.csv",
        ["scene_no", "scene_dir", "review_count"],
        scene_summary,
    )
    write_csv(
        OUTPUT_ROOT / "interactiveobj_assignment_summary.csv",
        ["scene_interactiveobj", "assigned_count"],
        interactive_summary,
    )


def write_link_tables() -> None:
    rows = [
        {
            "participant_id": participant_id(index),
            "url": f"{APP_URL}?bundle={participant_id(index)}",
            "places": 1,
        }
        for index in range(1, PARTICIPANT_COUNT + 1)
    ]
    write_csv(OUTPUT_ROOT / "participant_links_65.csv", ["participant_id", "url", "places"], rows)
    with (OUTPUT_ROOT / "link_prolific.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow([row["url"], row["places"]])


def main() -> None:
    scenes = load_scenes()
    if len(scenes) != 65:
        raise ValueError(f"Expected 65 scenes, found {len(scenes)}")
    OUTPUT_ROOT.mkdir(exist_ok=True)
    cost, assignment = best_assignment(scenes)
    long_rows, wide_rows = build_rows(assignment)
    long_fields = list(long_rows[0])
    wide_fields = list(wide_rows[0])
    write_csv(OUTPUT_ROOT / "participant_scene_assignment_long.csv", long_fields, long_rows)
    write_csv(OUTPUT_ROOT / "participant_scene_assignment_wide.csv", wide_fields, wide_rows)
    write_summaries(long_rows, cost)
    write_link_tables()
    print((OUTPUT_ROOT / "validation_report.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
