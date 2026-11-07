import json, sys, time, urllib.request

LEAGUE = 1030280  # your classic league ID
BASE = "https://fantasy.premierleague.com/api/"


def get(path):
    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print("retrying", path, e)
            time.sleep(5)
    sys.exit("FPL API unavailable, keeping the existing data.json")


events = get("bootstrap-static/")["events"]
done = max(e["id"] for e in events if e["finished"])  # last finished gameweek
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
