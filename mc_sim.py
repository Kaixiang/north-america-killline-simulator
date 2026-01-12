# -*- coding: utf-8 -*-
"""
北美斩杀线模拟器 v2.0 - Monte Carlo runner
Usage:
  python mc_sim.py --runs 2000 --seed 99000
Outputs:
  summary in stdout + event_trigger_report.csv in current folder
"""
import json, math, random, argparse, csv
from collections import Counter, defaultdict

TAGS = ['job', 'debt', 'housing', 'health', 'social', 'admin', 'car', 'money']

def clamp(v, lo, hi): 
    return max(lo, min(hi, v))

def effective_gain(base_gain, stat_value, cfg):
    if base_gain <= 0:
        return base_gain
    alpha = cfg["recovery"]["alpha"]
    floor = cfg["recovery"]["soft_floor"]
    penalty = max(0, floor - stat_value)
    return base_gain * math.exp(-alpha * penalty)

def cost_factor(month, cfg):
    infl = cfg["economy"].get("inflation_per_year", 0.0)
    return (1.0 + infl) ** (month / 12.0)

def wage_factor(month, cfg):
    wg = cfg["economy"].get("wage_growth_per_year", 0.0)
    return (1.0 + wg) ** (month / 12.0)

def apply_effects(stats, effects):
    for k, dv in effects.items():
        if k not in stats:
            continue
        stats[k] += dv
        if k in ["health","stress","family","friendship"]:
            stats[k] = int(round(clamp(stats[k], 0, 100)))

def add_state(active, sdef):
    sid = sdef["id"]
    if sdef["type"] == "counter":
        active.setdefault(sid, {"remaining": None})
        return
    if sdef.get("duration") is None:
        active.setdefault(sid, {"remaining": None})
        return
    dur = int(sdef.get("duration", 1))
    if sid in active:
        behavior = sdef.get("stacking","refresh")
        if behavior == "extend" and active[sid]["remaining"] is not None:
            active[sid]["remaining"] += dur
        else:
            active[sid]["remaining"] = dur
    else:
        active[sid] = {"remaining": dur}

def remove_state(active, sid):
    active.pop(sid, None)

def monthly_passive(stats, cfg):
    mp = cfg["recovery"]["monthly_passive"]
    base_h = mp["health_base_regen"] * (1.0 - stats["stress"]/140.0)
    dh = effective_gain(base_h, stats["health"], cfg)
    base_s = mp["stress_base_decay"] * (0.6 + stats["health"]/140.0 + stats["friendship"]/250.0)
    ds = -base_s
    base_r = mp["relationship_base_regen"] * (1.0 - stats["stress"]/140.0)
    dr = effective_gain(base_r, stats["family"], cfg)
    df = effective_gain(base_r, stats["friendship"], cfg)
    apply_effects(stats, {"health": int(round(dh)), "stress": int(round(ds)),
                          "family": int(round(dr)), "friendship": int(round(df))})

def tag_weights(active_states, state_tag_mult):
    w = {t: 1.0 for t in TAGS}
    for sid in active_states.keys():
        mods = state_tag_mult.get(sid)
        if not mods:
            continue
        for t, mult in mods.items():
            if t in w:
                w[t] *= mult
    for t in w:
        w[t] = clamp(w[t], 0.75, 1.55)
    return w

def weighted_choice(items, weights):
    total = sum(weights)
    r = random.random() * total
    acc = 0.0
    for it, w in zip(items, weights):
        acc += w
        if r <= acc:
            return it
    return items[-1]

def build_pools(events):
    pools = defaultdict(list)
    for ev in events:
        pools[ev["primary_tag"]].append(ev)
    return dict(pools)

def draw_event(pools, active_states, seen_counts, recent_list, cfg, state_tag_mult):
    tw = tag_weights(active_states, state_tag_mult)
    tag = weighted_choice(list(tw.keys()), list(tw.values()))
    pool = pools[tag]

    beta = cfg["draw"]["anti_repeat_beta"]
    recent_window = cfg["draw"]["recent_window"]
    recent_penalty = cfg["draw"]["recent_penalty"]

    weights = []
    candidates = []
    recent_set = set(recent_list[-recent_window:]) if recent_window > 0 else set()
    for ev in pool:
        sid = ev["id"]
        seen = seen_counts.get(sid, 0)
        w = ev.get("base_weight", 1.0) / ((1.0 + seen) ** beta)
        if sid in recent_set:
            w *= recent_penalty
        candidates.append(ev)
        weights.append(w)

    return weighted_choice(candidates, weights)

def apply_choice(stats, ch, active, counters, cfg, month, state_index):
    eff = dict(ch.get("effects", {}))
    cf = cost_factor(month, cfg)
    wf = wage_factor(month, cfg)

    # PAY_RENT action => charge current rent dynamically
    if ch.get("action") == "PAY_RENT":
        rent = int(round(cfg["economy"]["rent"] * cf))
        eff["money"] = eff.get("money", 0) - rent

    for k in ["health","family","friendship"]:
        if k in eff and eff[k] > 0:
            eff[k] = int(round(effective_gain(eff[k], stats[k], cfg)))

    if "money" in eff:
        m = eff["money"]
        if m > 0:
            m = m * cfg["balance"]["pos_money_mult"] * wf
            if "S_HIGH_INTEREST_LOAN" in active:
                m *= 0.85
        else:
            m = m * cfg["balance"]["neg_money_mult"] * cf
        eff["money"] = int(round(m))

    if "stress" in eff:
        eff["stress"] = int(round(eff["stress"] * cfg["balance"]["stress_mult"]))

    apply_effects(stats, eff)

    for sid in ch.get("add_states", []):
        add_state(active, state_index[sid])
    for sid in ch.get("remove_states", []):
        remove_state(active, sid)
        if sid == "S_RENT_ARREARS":
            counters["rent_arrears_months"] = 0

def apply_state_monthly(stats, active_states, counters, cfg, month, state_index):
    cf = cost_factor(month, cfg)
    wf = wage_factor(month, cfg)
    for sid in list(active_states.keys()):
        sdef = state_index[sid]

        # If laid off, no paycheck
        if sid == "S_PAYCHECK" and "S_LAYOFF" in active_states:
            pass
        else:
            eff = sdef.get("monthly_effect", {})
            eff2 = {}
            for k, v in eff.items():
                if k in ["health","family","friendship"] and v > 0:
                    eff2[k] = int(round(effective_gain(v, stats[k], cfg)))
                elif k == "money" and v > 0 and "S_HIGH_INTEREST_LOAN" in active_states:
                    eff2[k] = int(round(v * 0.85))
                else:
                    eff2[k] = v

            if "money" in eff2:
                m = eff2["money"]
                if m > 0:
                    eff2["money"] = int(round(m * cfg["balance"]["pos_money_mult"] * wf))
                else:
                    eff2["money"] = int(round(m * cfg["balance"]["neg_money_mult"] * cf))
            if "stress" in eff2:
                eff2["stress"] = int(round(eff2["stress"] * cfg["balance"]["stress_mult"]))
            apply_effects(stats, eff2)

        if sdef["type"] == "counter":
            if sid == "S_RENT_ARREARS":
                counters["rent_arrears_months"] = counters.get("rent_arrears_months", 0) + 1
            continue

        rem = active_states[sid].get("remaining", None)
        if rem is not None:
            rem -= 1
            if rem <= 0:
                del active_states[sid]
            else:
                active_states[sid]["remaining"] = rem

def month_end_rent(stats, active, counters, cfg, month, state_index):
    rent = int(round(cfg["economy"]["rent"] * cost_factor(month, cfg)))
    if "S_RENT_DUE" in active:
        if stats["money"] >= rent:
            apply_effects(stats, {"money": -rent, "stress": -1})
            remove_state(active, "S_RENT_DUE")
        else:
            remove_state(active, "S_RENT_DUE")
            add_state(active, state_index["S_RENT_ARREARS"])
    add_state(active, state_index["S_RENT_DUE"])

def fatal_strikes(stats, active_states, counters, cfg):
    strikes = 0
    if stats["money"] < cfg["thresholds"]["money_hard"]:
        strikes += 1
    if "S_RENT_ARREARS" in active_states and counters.get("rent_arrears_months", 0) >= cfg["thresholds"]["eviction_months"]:
        strikes += 1
    if stats["health"] <= 0 or stats["stress"] >= 100 or stats["family"] <= 0 or stats["friendship"] <= 0:
        strikes += 1
    return strikes

def simulate_one(events, states, cfg, seed):
    random.seed(seed)
    pools = build_pools(events)
    state_index = {s["id"]: s for s in states}
    state_tag_mult = {'S_LAYOFF': {'job': 1.6, 'debt': 1.35, 'money': 0.9, 'social': 0.95}, 'S_RENT_ARREARS': {'housing': 1.7, 'debt': 1.25, 'job': 1.1}, 'S_HIGH_INTEREST_LOAN': {'debt': 1.55, 'money': 0.85}, 'S_CREDIT_CARD_DEBT': {'debt': 1.25, 'money': 0.92}, 'S_INJURED': {'health': 1.55, 'job': 0.95}, 'S_HEALTH_SCARE': {'health': 1.35, 'admin': 1.1}, 'S_IMMIGRATION_ISSUE': {'admin': 1.55, 'job': 1.1}, 'S_CAR_BROKEN': {'car': 1.8, 'job': 1.05}, 'S_SOCIAL_ISOLATION': {'social': 1.45, 'health': 1.1}, 'S_WINDFALL_BUFFER': {'debt': 0.88, 'housing': 0.92, 'money': 1.12}, 'S_RENT_DUE': {'housing': 2.2}, 'S_TAX_DUE': {'admin': 2.0}, 'S_TRAFFIC_TICKET': {'car': 1.6, 'admin': 1.15}, 'S_COLLECTIONS_NOTICE': {'debt': 1.4, 'admin': 1.2}}

    stats = {
        "money": cfg["attrs"]["money"]["start"],
        "health": cfg["attrs"]["health"]["start"],
        "stress": cfg["attrs"]["stress"]["start"],
        "family": cfg["attrs"]["family"]["start"],
        "friendship": cfg["attrs"]["friendship"]["start"],
    }
    active = {}
    counters = {"rent_arrears_months": 0}
    seen_counts = {}
    recent = []
    event_counts = Counter()

    add_state(active, state_index["S_RENT_DUE"])
    add_state(active, state_index["S_PAYCHECK"])

    for month in range(cfg["max_months"]):
        monthly_passive(stats, cfg)
        apply_state_monthly(stats, active, counters, cfg, month, state_index)

        for _ in range(cfg["turns_per_month"]):
            ev = draw_event(pools, active, seen_counts, recent, cfg, state_tag_mult)
            event_counts[ev["id"]] += 1
            seen_counts[ev["id"]] = seen_counts.get(ev["id"], 0) + 1
            recent.append(ev["id"])
            if len(recent) > 40:
                recent = recent[-40:]

            ch = random.choice(ev["choices"])
            apply_choice(stats, ch, active, counters, cfg, month, state_index)

            if fatal_strikes(stats, active, counters, cfg) >= cfg["thresholds"]["collections_strikes"]:
                return False, len(seen_counts), event_counts

        month_end_rent(stats, active, counters, cfg, month, state_index)
        if fatal_strikes(stats, active, counters, cfg) >= cfg["thresholds"]["collections_strikes"]:
            return False, len(seen_counts), event_counts

    return True, len(seen_counts), event_counts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="events.json")
    ap.add_argument("--states", default="states.json")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--runs", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=99000)
    args = ap.parse_args()

    with open(args.events, "r", encoding="utf-8") as f:
        events = json.load(f)["events"]
    with open(args.states, "r", encoding="utf-8") as f:
        states = json.load(f)["states"]
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)["config"]

    wins = 0
    uniqs = []
    total_counts = Counter()
    for i in range(args.runs):
        ok, uniq, ec = simulate_one(events, states, cfg, args.seed+i)
        wins += int(ok)
        uniqs.append(uniq)
        total_counts.update(ec)

    win_rate = wins / args.runs
    uniq_ge_100 = sum(1 for u in uniqs if u >= 100) / args.runs
    uniq_avg = sum(uniqs)/args.runs
    total_draws = sum(total_counts.values())
    top10 = sum(c for _, c in total_counts.most_common(10)) / total_draws if total_draws else 0.0
    top25 = sum(c for _, c in total_counts.most_common(25)) / total_draws if total_draws else 0.0

    print({
        "runs": args.runs,
        "win_rate": win_rate,
        "uniq_ge_100": uniq_ge_100,
        "uniq_avg": uniq_avg,
        "top10_share": top10,
        "top25_share": top25,
        "uniq_p10": sorted(uniqs)[int(0.10*args.runs)],
        "uniq_p50": sorted(uniqs)[int(0.50*args.runs)],
        "uniq_p90": sorted(uniqs)[int(0.90*args.runs)],
    })

    # export trigger report
    with open("event_trigger_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["event_id","triggers"])
        for eid, c in total_counts.most_common():
            w.writerow([eid, c])

if __name__ == "__main__":
    main()
