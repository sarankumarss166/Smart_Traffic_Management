import cv2, json, time, threading, os
from ultralytics import YOLO

# ----------------------------
# Video feeds per junction
# ----------------------------
VIDEO_FEEDS = {
    "Fun Mall": {
        "north": "videos/Fun Mall_north.mp4",
        "east": "videos/Fun Mall_east.mp4",
        "south": "videos/Fun Mall_south.mp4",
        "west": "videos/Fun Mall_west.mp4"
    },
    "Gandhipuram": {
        "north": "videos/Gandhipuram_north.mp4",
        "east": "videos/Gandhipuram_east.mp4",
        "south": "videos/gandhipuram_south.mp4",
        "west": "videos/Gandhipuram_west.mp4"
    },
    "Navaindia": {
        "north": "videos/Navaindia_north.mp4",
        "east": "videos/Navaindia_east.mp4",
        "south": "videos/Navaindia_south.mp4",
        "west": "videos/navaindia_west.mp4"
    },
    "Peelamedu": {
        "north": "videos/Peelamedu_north.mp4",
        "east": "videos/Peelamedu_east.mp4",
        "south": "videos/Peelamedu_south.mp4",
        "west": "videos/Peelamedu_west.mp4"
    }
}

STATE_FILE = "state.json"
LANES = ["north", "east", "south", "west"]

# ----------------------------
# Default state
# ----------------------------
DEFAULT_STATE = {
    jn: {
        "lane_counts": {ln: 0 for ln in LANES},
        "lane_times": {ln: 60 for ln in LANES},
        "current_green": "north",
        "mode": "Auto",
        "timer_end": time.time() + 60  # start with base 60
    }
    for jn in VIDEO_FEEDS
}

# ----------------------------
# YOLO setup
# ----------------------------
model = YOLO("yolov8n.pt")
caps = {j: {l: cv2.VideoCapture(p) for l, p in lanes.items()} for j, lanes in VIDEO_FEEDS.items()}
state_lock = threading.Lock()

# ----------------------------
# Safe JSON write
# ----------------------------
def safe_write_state(state):
    tmp_file = STATE_FILE + ".tmp"
    with open(tmp_file, "w") as f:
        json.dump(state, f)
    os.replace(tmp_file, STATE_FILE)

# ----------------------------
# Update vehicle count (only counts, not green/timer)
# ----------------------------
def update_state(junction, lane, count):
    with state_lock:
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except:
            state = {}

        # Ensure junction exists without overwriting mode/green
        if junction not in state:
            state[junction] = DEFAULT_STATE[junction].copy()
            state[junction]["lane_counts"] = {ln: 0 for ln in LANES}

        # ✅ Only update counts, keep green/timer untouched
        if "lane_counts" not in state[junction]:
            state[junction]["lane_counts"] = {ln: 0 for ln in LANES}
        state[junction]["lane_counts"][lane] = count

        # Save updated state safely
        safe_write_state(state)

# ----------------------------
# Frame generator (YOLO + stream)
# ----------------------------
def generate_frames(junction, lane):
    cap = caps[junction][lane]
    vehicle_classes = [2, 3, 5, 7]  # car, motorcycle, bus, truck

    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        results = model.predict(frame, verbose=False)[0]

        # Filter only vehicles
        boxes, classes = [], []
        if hasattr(results.boxes, 'xyxy') and hasattr(results.boxes, 'cls'):
            boxes_all = results.boxes.xyxy.cpu().numpy()
            cls_all = results.boxes.cls.cpu().numpy()
            for box, cls in zip(boxes_all, cls_all):
                if int(cls) in vehicle_classes:
                    boxes.append(box)
                    classes.append(int(cls))

        count = len(boxes)

        # Draw boxes
        for box in boxes:
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # Update vehicle count in state
        update_state(junction, lane, count)

        # Encode frame
        _, buffer = cv2.imencode('.jpg', frame)
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
        )
