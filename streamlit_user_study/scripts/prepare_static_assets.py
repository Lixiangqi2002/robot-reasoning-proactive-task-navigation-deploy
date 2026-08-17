from __future__ import annotations

import shutil
from pathlib import Path

try:
    import streamlit as st
except ModuleNotFoundError:
    st = None


SOURCE_ROOT = Path("/media/selina-xiangqi/New Volume/dsg_dataset/user_study_data")
DEST_ROOT = Path(__file__).resolve().parents[1] / "assets"

NEEDED_FILES = [
    "manifest.json",
    "study_2a_stimulus_raw_rgb_plus_three_pair_crops_refined.png",
    "study_1_proposed_hoir1_parsed_output.json",
    "study_1_proposed_hoir1_crop.png",
    "study_1_proposed_full_rgb.png",
    "study_2b_text_summary_refined.json",
    "study_3b_option_a_rgb_traj.png",
    "study_3b_option_a_bev.png",
    "study_3b_option_b_rgb_traj.png",
    "study_3b_option_b_bev.png",
    "study_3b_option_c_rgb_traj.png",
    "study_3b_option_c_bev.png",
    "study_3b_goal_path_rgb_overlay_refined.png",
    "study_3b_goal_path_reference_map_refined.png",
]


def trial_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def main() -> None:
    if st is not None:
        st.error(
            "This helper script prepares local static assets and is not the Streamlit app entry point. "
            "Please deploy `streamlit_app.py` or `streamlit_user_study/app.py` instead."
        )
        return
    if not SOURCE_ROOT.exists():
        print(f"Source root does not exist: {SOURCE_ROOT}")
        print("Run this helper only on the local machine that has the full user_study_data directory.")
        return

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing: list[str] = []

    for trial_dir in trial_dirs(SOURCE_ROOT):
        out_dir = DEST_ROOT / trial_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        for filename in NEEDED_FILES:
            src = trial_dir / filename
            dst = out_dir / filename
            if src.exists():
                shutil.copy2(src, dst)
                copied += 1
            else:
                missing.append(f"{trial_dir.name}/{filename}")

    print(f"Copied {copied} files into {DEST_ROOT}")
    print(f"Missing {len(missing)} expected files")
    for item in missing[:50]:
        print(f"Missing: {item}")
    if len(missing) > 50:
        print(f"... and {len(missing) - 50} more")


if __name__ == "__main__":
    main()
