import json, sys, time, urllib.request

LEAGUE = 1030280  # your classic league ID
BASE = "https://fantasy.premierleague.com/api/"
SHEET = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTmd8NEu8an7vF7sNRfGf8lj3bp41AfffGl_fsBFJiZgSMIxhSrwa7E_6CiRInFKXWy8j6G3fcDyKg1/pub?gid=0&single=true&output=csv"

# Save a copy of the accumulator Google Sheet (the page falls back to this copy)
try:
    req = urllib.request.Request(SHEET, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8")
    if "Selected Team" in text:
        with open("accumulator.csv", "w", encoding="utf-8") as f:
            f.write(text)
        print("Saved accumulator.csv")
except Exception as e:
    print("Could not fetch the accumulator sheet:", e)


def get(path):
    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print("retrying", path, e)
            time.sleep(5)
    print("FPL API unavailable, keeping the existing data.json")
    sys.exit(0)


events = get("bootstrap-static/")["events"]
done = max(e["id"] for e in events if e["finished"] or e.get("data_checked"))  # last finished gameweek
results = get(f"leagues-classic/{LEAGUE}/standings/")["standings"]["results"]

out = {}
for m in results:
    h = get(f"entry/{m['entry']}/history/")
    out[m["entry_name"]] = {
        "manager": m["player_name"],
        "gws": [
            [g["total_points"], g["event_transfers_cost"], g["points_on_bench"],
             g["event_transfers"], g["value"], g["bank"], g["overall_rank"]]
            for g in h["current"] if g["event"] <= done
        ],
        "chips": [[c["name"], c["event"]] for c in h["chips"] if c["event"] <= done],
    }

out["_updated"] = time.strftime("%d %b %Y")
with open("data.json", "w") as f:
    json.dump(out, f)
print("Saved data up to GW", done)
