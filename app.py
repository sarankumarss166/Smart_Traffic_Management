from flask import Flask, render_template, request, redirect, url_for, flash, session, Response
import json, time, threading
from processor import generate_frames, state_lock   # import lock from processor

app = Flask(__name__)
app.secret_key = 'your_secret_key'

STATE_FILE = "state.json"
LANES = ["north", "east", "south", "west"]

VALID_EMAIL = "saran@gmail.com"
VALID_PASSWORD = "qwerty"

BASE_TIME = 60          # base green time for each lane
EXTRA_TIME_POOL = 60    # extra time distributed dynamically


# ------------------ LOGIN ROUTES ------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        if email == VALID_EMAIL and password == VALID_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            flash("Invalid email or password!")
            return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


# ------------------ DASHBOARD ------------------
@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    try:
        with state_lock:
            with open(STATE_FILE, "r") as f:
                junctions = list(json.load(f).keys())
    except:
        junctions = []
    return render_template("index.html", junctions=junctions)


@app.route("/junction/<name>", methods=["GET", "POST"])
def junction(name):
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    with state_lock:
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}

        if name not in state:
            state[name] = {
                "lane_counts": {ln: 0 for ln in LANES},
                "lane_times": {ln: BASE_TIME for ln in LANES},
                "current_green": "north",
                "mode": "Auto",
                "timer_end": time.time() + BASE_TIME
            }

        if request.method == "POST":
            # Force lane (Manual)
            lane = request.form.get("force_lane")
            if lane:
                state[name]["mode"] = "Manual"
                state[name]["current_green"] = lane
                state[name]["timer_end"] = time.time() + 10**10  # very long

            # Switch Auto (resume properly, not reset to north)
            if request.form.get("switch_auto"):
                state[name]["mode"] = "Auto"
                current_lane = state[name]["current_green"]
                lane_times = state[name].get("lane_times", {ln: BASE_TIME for ln in LANES})
                state[name]["timer_end"] = time.time() + lane_times.get(current_lane, BASE_TIME)

            # Emergency Lane
            emergency_lane = request.form.get("emergency_lane")
            if emergency_lane:
                state[name]["mode"] = "Emergency"
                state[name]["current_green"] = emergency_lane
                state[name]["timer_end"] = time.time() + 120

            # Stop Signals
            if request.form.get("stop_signals"):
                state[name]["mode"] = "Stop"
                state[name]["current_green"] = None
                state[name]["timer_end"] = 0

            # Start Signals (fresh auto cycle → start north)
            if request.form.get("start_signals"):
                state[name]["mode"] = "Auto"
                state[name]["current_green"] = "north"
                state[name]["timer_end"] = time.time() + BASE_TIME

            with open(STATE_FILE, "w") as f:
                json.dump(state, f)

            return redirect(url_for("junction", name=name))

    return render_template(
        "junction.html",
        junction=name,
        lane_counts=state[name]["lane_counts"],
        current_green=state[name]["current_green"],
        lanes=LANES,
        mode=state[name]["mode"],
        timer_end=state[name]["timer_end"],
        lane_times=state[name].get("lane_times", {ln: BASE_TIME for ln in LANES})
    )


# ------------------ STATE / VIDEO ------------------
@app.route("/state/<junction>")
def get_state(junction):
    with state_lock:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    return state.get(junction, {})


@app.route("/video/<junction>/<lane>")
def video(junction, lane):
    return Response(generate_frames(junction, lane),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# ------------------ AUTO SIGNAL LOOP ------------------
def auto_loop():
    while True:
        try:
            with state_lock:
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)

                now = time.time()
                changed = False

                for jn, data in state.items():
                    # --------- Emergency Handling ---------
                    if data["mode"] == "Emergency":
                        if now >= data.get("timer_end", 0):
                            # After 120s, switch back to Auto
                            data["mode"] = "Auto"
                            current_lane = data.get("current_green", "north")
                            lane_times = data.get("lane_times", {ln: BASE_TIME for ln in LANES})
                            data["timer_end"] = now + lane_times.get(current_lane, BASE_TIME)
                            changed = True
                        continue  # skip auto switching this cycle

                    # --------- Auto Handling ---------
                    if data["mode"] != "Auto":
                        continue

                    current_lane = data["current_green"]
                    timer_end = data.get("timer_end", 0)

                    if now >= timer_end:
                        # ---- Round-robin lane switching ----
                        next_index = (LANES.index(current_lane) + 1) % len(LANES)
                        next_lane = LANES[next_index]

                        # ---- Dynamic timing ----
                        lane_counts = data.get("lane_counts", {ln: 0 for ln in LANES})
                        total_count = sum(lane_counts.values())

                        lane_times = {}
                        if total_count == 0:
                            for ln in LANES:
                                lane_times[ln] = BASE_TIME
                        else:
                            for ln in LANES:
                                share = lane_counts[ln] / total_count
                                lane_times[ln] = BASE_TIME + int(share * EXTRA_TIME_POOL)

                        # Update state
                        data["current_green"] = next_lane
                        data["lane_times"] = lane_times
                        data["timer_end"] = now + lane_times[next_lane]

                        changed = True

                if changed:
                    with open(STATE_FILE, "w") as f:
                        json.dump(state, f)

        except Exception as e:
            print("Auto loop error:", e)

        time.sleep(0.5)


threading.Thread(target=auto_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True)
