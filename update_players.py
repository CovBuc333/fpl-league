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
    cap_total = missed = missed_weeks = 0
    opt_lost, perfect, worst = 0, 0, {"gw": 0, "lost": 0}
    chip_by_gw, cap_by_gw, pts_by_gw, picks_by_gw = {}, {}, {}, {}
    last = []
    wi_cap, wi_xi = [], []  # what-if candidates: captain swaps and best-XI weeks
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
            t = tot.setdefault(el, {"pts": 0, "starts": 0, "caps": 0})
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
            tot[el]["caps"] += 1
            topel = max(starters, key=lambda x: raw[gw].get(x, 0))
            top = raw[gw].get(topel, 0)
            if top > cr:
                missed += (top - cr) * (mu - 1)
                missed_weeks += 1
                wi_cap.append({"t": "cap", "gw": gw, "d": (top - cr) * (mu - 1),
                               "a": players[el], "ar": cr, "b": players[topel], "br": top})
        chip_by_gw[gw] = d.get("active_chip")
        picks_by_gw[gw] = picks
        pts_by_gw[gw] = gw_pts
        if capel and starters:
            cap_by_gw[gw] = (capel[0], mult[capel[0]])
        # optimal XI (bench boost weeks: all 15 count, so nothing to lose)
        if not bboost:
            lost = optimal([(pos_of[p["element"]], raw[gw].get(p["element"], 0)) for p in picks]) - xi_raw
            lost = max(lost, 0)
            if lost > 0:
                bench_els = [p["element"] for p in picks if p["element"] not in starters]
                if bench_els:
                    bn = max(bench_els, key=lambda e: raw[gw].get(e, 0))
                    wi_xi.append({"t": "xi", "gw": gw, "d": lost, "n": players[bn], "r": raw[gw].get(bn, 0)})
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

    # Chip efficiency (wildcard excluded): points gained from each chip
    chips = []
    for gw, chip in chip_by_gw.items():
        if chip == "3xc" and gw in cap_by_gw:
            el, _ = cap_by_gw[gw]
            g = raw[gw].get(el, 0)  # the extra multiple on top of a normal captain
            chips.append({"chip": "3xc", "gw": gw, "gain": g, "note": f"{players[el]} scored {g}"})
        elif chip == "bboost":
            g = sum(raw[gw].get(p["element"], 0) for p in picks_by_gw[gw] if p["position"] >= 12)
            chips.append({"chip": "bboost", "gw": gw, "gain": g, "note": f"bench scored {g}"})
        elif chip == "freehit":
            prev = picks_by_gw.get(gw - 1)
            if prev:
                cf = sum(raw[gw].get(p["element"], 0) * (2 if p["multiplier"] >= 2 else 1)
                         for p in prev if p["position"] <= 11)
                chips.append({"chip": "freehit", "gw": gw, "gain": pts_by_gw[gw] - cf,
                              "note": f"{pts_by_gw[gw]} pts vs {cf} with the previous team"})
            else:
                chips.append({"chip": "freehit", "gw": gw, "gain": 0, "note": "no previous team to compare"})
    chips.sort(key=lambda c: c["gw"])

    out_teams[name] = {
        "manager": mgr,
        "top": [{"n": players[el], "pts": v["pts"], "starts": v["starts"], "caps": v["caps"]}
                for el, v in top5],
        "cap": {
            "total": cap_total, "missed": missed,
            "missed_weeks": missed_weeks, "weeks": len(caps),
            "best": max(caps, key=lambda c: c["raw"]) if caps else None,
            "worst": min(caps, key=lambda c: c["raw"]) if caps else None,
        },
        "bench": {"lost": opt_lost, "perfect": perfect, "worst": worst},
        "chips": chips,
        # what-if candidates (points that a different decision would have added); the page turns these into league positions
        "wi": sorted(wi_cap, key=lambda w: -w["d"])[:8] + sorted(wi_xi, key=lambda w: -w["d"])[:8],
    }

    # Transfers: did the player bought outscore the player sold?
    skip = {g for g, c in chip_by_gw.items() if c in ("wildcard", "freehit")}
    for t in get(f"entry/{entry}/transfers/"):
        e = t["event"]
        if e > done or e in skip:
            continue

        def win(el, n):
            return sum(raw[g].get(el, 0) for g in range(e, e + n))

        full = e + 2 <= done
        transfers.append({
            "mgr": mgr, "gw": e, "in": players[t["element_in"]], "out": players[t["element_out"]],
            "a1": win(t["element_in"], 1), "b1": win(t["element_out"], 1),
            "a3": win(t["element_in"], 3) if full else None,
            "b3": win(t["element_out"], 3) if full else None,
        })

owners = {}
for mgr, sq in squads.items():
    for el in sq:
        owners.setdefault(el, []).append(mgr)
own = sorted(({"n": players[el], "owners": o} for el, o in owners.items()),
             key=lambda x: (-len(x["owners"]), x["n"]))

transfers.sort(key=lambda x: (-x["gw"], x["mgr"]))
out = {
    "_updated": time.strftime("%d %b %Y"),
    "gw": done,
    "mismatch_weeks": mismatch,
    "teams": out_teams,
    "regrets": sorted(regrets, key=lambda r: -r["raw"])[:6],
    "own": own,
    "tx": transfers,
}
with open("player_stats.json", "w") as f:
    json.dump(out, f)
print("Saved player_stats.json up to GW", done)
