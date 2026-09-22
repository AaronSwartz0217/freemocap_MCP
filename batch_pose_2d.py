import os
import sys
import cv2
import json
import mediapipe as mp
import numpy as np

INPUT_DIR = r"D:\本地动捕环境\图像资源"
OUTPUT_DIR = r"D:\本地动捕环境\freemocap_MCP\mocap_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles

POSE_CONNECTIONS = mp_pose.POSE_CONNECTIONS

COLORS = {
    "face": (255, 0, 0),
    "torso": (0, 0, 255),
    "left_arm": (255, 0, 0),
    "right_arm": (0, 255, 0),
    "left_leg": (0, 165, 255),
    "right_leg": (255, 255, 0),
}

def get_connection_color(idx1, idx2):
    face = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    torso = {11, 12, 23, 24}
    left_arm = {11, 13, 15, 17, 19, 21}
    right_arm = {12, 14, 16, 18, 20, 22}
    left_leg = {23, 25, 27, 29, 31}
    right_leg = {24, 26, 28, 30, 32}
    if idx1 in face or idx2 in face:
        return COLORS["face"]
    if (idx1 in torso and idx2 in torso):
        return COLORS["torso"]
    if idx1 in left_arm or idx2 in left_arm:
        return COLORS["left_arm"]
    if idx1 in right_arm or idx2 in right_arm:
        return COLORS["right_arm"]
    if idx1 in left_leg or idx2 in left_leg:
        return COLORS["left_leg"]
    if idx1 in right_leg or idx2 in right_leg:
        return COLORS["right_leg"]
    return (255, 255, 255)

def detect_and_draw(image_path, output_dir):
    img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print(f"[SKIP] Cannot read: {image_path}")
        return None
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    with mp_pose.Pose(static_image_mode=True, model_complexity=1, enable_segmentation=False, min_detection_confidence=0.5) as pose:
        results = pose.process(rgb)

    skeleton = np.zeros((h, w, 3), dtype=np.uint8)
    landmarks_data = []

    if results.pose_landmarks:
        landmarks = results.pose_landmarks.landmark
        for i, lm in enumerate(landmarks):
            cx, cy = int(lm.x * w), int(lm.y * h)
            cv2.circle(skeleton, (cx, cy), 5, (255, 255, 255), -1)
            cv2.circle(skeleton, (cx, cy), 5, (0, 0, 0), 1)
            landmarks_data.append({"index": i, "x": round(lm.x, 4), "y": round(lm.y, 4), "visibility": round(lm.visibility, 4)})

        for conn in POSE_CONNECTIONS:
            idx1, idx2 = conn
            if idx1 < len(landmarks) and idx2 < len(landmarks):
                l1, l2 = landmarks[idx1], landmarks[idx2]
                p1 = (int(l1.x * w), int(l1.y * h))
                p2 = (int(l2.x * w), int(l2.y * h))
                color = get_connection_color(idx1, idx2)
                cv2.line(skeleton, p1, p2, color, 3)

    base = os.path.splitext(os.path.basename(image_path))[0]
    skel_path = os.path.join(output_dir, f"{base}_skeleton.png")
    cv2.imwrite(skel_path, skeleton)

    comp = np.hstack([img, skeleton])
    comp_path = os.path.join(output_dir, f"{base}_comparison.png")
    cv2.imwrite(comp_path, comp)

    json_path = os.path.join(output_dir, f"{base}_landmarks.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"success": True, "detector": "mediapipe_pose", "landmark_count": len(landmarks_data), "landmarks": landmarks_data}, f, ensure_ascii=False, indent=2)

    print(f"[OK] {os.path.basename(image_path)} -> {len(landmarks_data)} landmarks")
    print(f"     skeleton: {skel_path}")
    print(f"     comparison: {comp_path}")
    print(f"     json: {json_path}")
    return skel_path

exts = (".jpg", ".jpeg", ".png", ".jfif", ".bmp", ".webp")
files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(exts)]
print(f"Found {len(files)} images in {INPUT_DIR}")
print("=" * 60)

for f in sorted(files):
    detect_and_draw(os.path.join(INPUT_DIR, f), OUTPUT_DIR)

print("=" * 60)
print(f"Done. Outputs in: {OUTPUT_DIR}")
