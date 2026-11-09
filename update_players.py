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


def optimal(sq):
    """Best possible starting XI points from a 15-man squad [(position, points)].
    FPL rules: 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD, 11 players in total."""
    by = {1: [], 2: [], 3: [], 4: []}
    for pos, pts in sq:
        by[pos].append(pts)
    for k in by:
        by[k].sort(reverse=True)
    best = 0
    gk = by[1][0] if by[1] else 0
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if 1 <= f <= 3 and len(by[2]) >= d and len(by[3]) >= m and len(by[4]) >= f:
                best = max(best, gk + sum(by[2][:d]) + sum(by[3][:m]) + sum(by[4][:f]))
    return best


boot = get("bootstrap-static/")
players = {e["id"]: e["web_name"] for e in boot["elements"]}
pos_of = {e["id"]: e["element_type"] for e in boot["elements"]}
done = max(e["id"] for e in boot["events"] if e["finished"] or e.get("data_checked"))
results = get(f"leagues-classic/{LEAGUE}/standings/")["standings"]["results"]

# Points every player scored in every finished gameweek
raw = {}
for gw in range(1, done + 1):
    raw[gw] = {x["id"]: x["stats"]["total_points"] for x in get(f"event/{gw}/live/")["elements"]}

out_teams, regrets, transfers, squads = {}, [], [], {}
mismatch = 0

for m in results:
    mgr, name, entry = m["player_name"], m["entry_name"], m["entry"]
    tot, caps = {}, []
    cap_total = cap_gain = missed = missed_weeks = 0
    opt_lost, perfect, worst = 0, 0, {"gw": 0, "lost": 0}
    last = []
    for gw in range(1, done + 1):
        d = get(f"entry/{entry}/event/{gw}/picks/")
        picks = d["picks"]
        mult = {p["element"]: p["multiplier"] for p in picks}
        for s in d.get("automatic_subs", []):  # auto-subs: player out stops counting, player in starts
            mult[s["element_out"]] = 0
            mult[s["element_in"]] = 1
        bboost = d.get("active_chip") == "bboost"
        gw_pts = xi_raw = 0
        starters = []
        for p in picks:
            el, mu = p["element"], mult.get(p["element"], 0)
            pts = raw[gw].get(el, 0)
            t = tot.setdefault(el, {"pts": 0, "starts": 0, "caps": 0, "capPts": 0})
            if mu > 0:
                t["pts"] += pts * mu
                t["starts"] += 1
                gw_pts += pts * mu
                xi_raw += pts
                starters.append(el)
            elif not bboost and pts > 0:
                regrets.append({"mgr": mgr, "gw": gw, "n": players[el], "raw": pts})
        # captaincy
        capel = [p["element"] for p in picks if mult.get(p["element"], 0) >= 2]
        if capel and starters:
            el, mu = capel[0], mult[capel[0]]
            cr = raw[gw].get(el, 0)
            caps.append({"gw": gw, "n": players[el], "raw": cr})
            cap_total += cr * mu
            cap_gain += cr * (mu - 1)
            tot[el]["caps"] += 1
            tot[el]["capPts"] += cr * (mu - 1)
            top = max(raw[gw].get(x, 0) for x in starters)
            if top > cr:
                missed += (top - cr) * (mu - 1)
                missed_weeks += 1
        # optimal XI (bench boost weeks: all 15 count, so nothing to lose)
        if not bboost:
            lost = optimal([(pos_of[p["element"]], raw[gw].get(p["element"], 0)) for p in picks]) - xi_raw
            lost = max(lost, 0)
            opt_lost += lost
            if lost == 0:
                perfect += 1
            if lost > worst["lost"]:
                worst = {"gw": gw, "lost": lost}
        else:
            perfect += 1
        eh = d.get("entry_history", {})
        if gw_pts not in (eh.get("points"), eh.get("points", 0) + eh.get("event_transfers_cost", 0)):
            mismatch += 1
            print("Check: GW", gw, mgr, "computed", gw_pts, "FPL says", eh.get("points"))
        last = [p["element"] for p in picks]
    squads[mgr] = last
    top5 = sorted(tot.items(), key=lambda kv: -kv[1]["pts"])[:5]
    out_teams[name] = {
        "manager": mgr,
        "top": [{"n": players[el], "pts": v["pts"], "starts": v["starts"],
                 "caps": v["caps"], "capPts": v["capPts"]} for el, v in top5],
        "cap": {
            "total": cap_total, "gain": cap_gain, "missed": missed,
            "missed_weeks": missed_weeks, "weeks": len(caps),
            "best": max(caps, key=lambda c: c["raw"]) if caps else None,
            "worst": min(caps, key=lambda c: c["raw"]) if caps else None,
        },
        "bench": {"lost": opt_lost, "perfect": perfect, "worst": worst},
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
