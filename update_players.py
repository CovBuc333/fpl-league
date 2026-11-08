import json, sys, time, urllib.request

LEAGUE = 1030280  # your classic league ID
BASE = "https://fantasy.premierleague.com/api/"


def get(path):
    for attempt in range(3):
        try:
            req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(0.25)  # be gentle with the FPL servers
            return data
        except Exception as e:
            print("retrying", path, e)
            time.sleep(5)
    print("FPL API unavailable, keeping the existing player_stats.json")
    sys.exit(0)


boot = get("bootstrap-static/")
players = {e["id"]: e["web_name"] for e in boot["elements"]}
done = max(e["id"] for e in boot["events"] if e["finished"])
results = get(f"leagues-classic/{LEAGUE}/standings/")["standings"]["results"]

# Points every player scored in every finished gameweek
raw = {}
for gw in range(1, done + 1):
    raw[gw] = {x["id"]: x["stats"]["total_points"] for x in get(f"event/{gw}/live/")["elements"]}

out_teams, regrets, transfers, squads = {}, [], [], {}
mismatch = 0

for m in results:
    mgr, name, entry = m["player_name"], m["entry_name"], m["entry"]
    tot, caps, cap_gain = {}, [], 0
    last = []
    for gw in range(1, done + 1):
        d = get(f"entry/{entry}/event/{gw}/picks/")
        picks = d["picks"]
        mult = {p["element"]: p["multiplier"] for p in picks}
        for s in d.get("automatic_subs", []):  # auto-subs: player out stops counting, player in starts
            mult[s["element_out"]] = 0
            mult[s["element_in"]] = 1
        gw_pts = 0
        for p in picks:
            el, mu = p["element"], mult.get(p["element"], 0)
            pts = raw[gw].get(el, 0)
            t = tot.setdefault(el, {"pts": 0, "starts": 0})
            if mu > 0:
                t["pts"] += pts * mu
                t["starts"] += 1
                gw_pts += pts * mu
            elif d.get("active_chip") != "bboost" and pts > 0:
                regrets.append({"mgr": mgr, "gw": gw, "n": players[el], "raw": pts})
        capel = [p["element"] for p in picks if mult.get(p["element"], 0) >= 2]
        if capel:
            el = capel[0]
            caps.append({"gw": gw, "n": players[el], "raw": raw[gw].get(el, 0)})
            cap_gain += raw[gw].get(el, 0) * (mult[el] - 1)
        eh = d.get("entry_history", {})
        if gw_pts not in (eh.get("points"), eh.get("points", 0) + eh.get("event_transfers_cost", 0)):
            mismatch += 1
            print("Check: GW", gw, mgr, "computed", gw_pts, "FPL says", eh.get("points"))
        last = [p["element"] for p in picks]
    squads[mgr] = last
    top = sorted(tot.items(), key=lambda kv: -kv[1]["pts"])[:5]
    out_teams[name] = {
        "manager": mgr,
        "top": [{"n": players[el], "pts": v["pts"], "starts": v["starts"]} for el, v in top],
        "cap": {
            "gain": cap_gain,
            "best": max(caps, key=lambda c: c["raw"]) if caps else None,
            "worst": min(caps, key=lambda c: c["raw"]) if caps else None,
        },
    }
    for t in get(f"entry/{entry}/transfers/"):
        if t["event"] > done:
            continue
        span = range(t["event"], done + 1)
        net = sum(raw[g].get(t["element_in"], 0) for g in span) - sum(raw[g].get(t["element_out"], 0) for g in span)
        transfers.append({"mgr": mgr, "gw": t["event"], "in": players[t["element_in"]],
                          "out": players[t["element_out"]], "net": net})

owners = {}
for mgr, sq in squads.items():
    for el in sq:
        owners.setdefault(el, []).append(mgr)
own = sorted(({"n": players[el], "owners": o} for el, o in owners.items()),
             key=lambda x: (-len(x["owners"]), x["n"]))

transfers.sort(key=lambda x: -x["net"])
out = {
    "_updated": time.strftime("%d %b %Y"),
    "gw": done,
    "mismatch_weeks": mismatch,
    "teams": out_teams,
    "regrets": sorted(regrets, key=lambda r: -r["raw"])[:6],
    "own": own,
    "best_tx": transfers[:3],
    "worst_tx": transfers[::-1][:3],
}
with open("player_stats.json", "w") as f:
    json.dump(out, f)
print("Saved player_stats.json up to GW", done)
