#!/usr/bin/env python3
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.sleeper.app/v1"
LEAGUE_ID = os.getenv("SLEEPER_LEAGUE_ID", "1314667834135040000")
USERNAME = os.getenv("SLEEPER_USERNAME", "Cpablo1182")
DATA_DIR = Path("data")
UA = "Sleeper-Bridge/1.1"

def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)

def player_summary(p):
    if not p:
        return None
    return {
        "player_id": p.get("player_id"),
        "full_name": p.get("full_name"),
        "position": p.get("position"),
        "fantasy_positions": p.get("fantasy_positions"),
        "team": p.get("team"),
        "age": p.get("age"),
        "years_exp": p.get("years_exp"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "injury_body_part": p.get("injury_body_part"),
        "depth_chart_position": p.get("depth_chart_position"),
        "depth_chart_order": p.get("depth_chart_order"),
        "active": p.get("active"),
    }

def resolve_ids(ids, players):
    return [players.get(pid) or {"player_id": pid, "full_name": pid} for pid in (ids or [])]

def build_future_pick_ledger(rosters, traded_picks, league):
    current_season = int(league.get("season") or datetime.now().year)
    rounds = int((league.get("settings") or {}).get("draft_rounds") or 4)
    seasons = list(range(current_season + 1, current_season + 4))

    ledger = {}
    for r in rosters:
        rid = int(r["roster_id"])
        ledger[str(rid)] = []
        for season in seasons:
            for rnd in range(1, rounds + 1):
                ledger[str(rid)].append({
                    "season": str(season),
                    "round": rnd,
                    "original_roster_id": rid,
                    "current_owner_roster_id": rid,
                })

    by_key = {}
    for owner, picks in ledger.items():
        for p in picks:
            by_key[(p["season"], p["round"], p["original_roster_id"])] = p

    for tp in traded_picks:
        try:
            key = (str(tp.get("season")), int(tp.get("round")), int(tp.get("roster_id")))
            owner_id = int(tp.get("owner_id"))
        except (TypeError, ValueError):
            continue
        if key not in by_key:
            pick = {
                "season": key[0],
                "round": key[1],
                "original_roster_id": key[2],
                "current_owner_roster_id": owner_id,
            }
            by_key[key] = pick
        else:
            by_key[key]["current_owner_roster_id"] = owner_id

    output = {str(int(r["roster_id"])): [] for r in rosters}
    for p in by_key.values():
        output.setdefault(str(p["current_owner_roster_id"]), []).append(p)
    for picks in output.values():
        picks.sort(key=lambda x: (x["season"], x["round"], x["original_roster_id"]))
    return output

def main():
    account = get(f"/user/{USERNAME}")
    league = get(f"/league/{LEAGUE_ID}")
    users = get(f"/league/{LEAGUE_ID}/users")
    rosters = get(f"/league/{LEAGUE_ID}/rosters")
    traded_picks = get(f"/league/{LEAGUE_ID}/traded_picks")
    drafts = get(f"/league/{LEAGUE_ID}/drafts")
    nfl_state = get("/state/nfl")

    all_players = get("/players/nfl")
    roster_player_ids = set()
    for r in rosters:
        roster_player_ids.update(r.get("players") or [])
        roster_player_ids.update(r.get("reserve") or [])
        roster_player_ids.update(r.get("taxi") or [])
        roster_player_ids.update(r.get("starters") or [])
    players = {pid: player_summary(all_players.get(pid)) for pid in sorted(roster_player_ids)}

    user_by_id = {u.get("user_id"): u for u in users}
    enriched_rosters = []
    compact_rosters = []
    for r in rosters:
        owner = user_by_id.get(r.get("owner_id")) or {}
        owner_info = {
            "user_id": owner.get("user_id"),
            "username": owner.get("username"),
            "display_name": owner.get("display_name"),
            "team_name": (owner.get("metadata") or {}).get("team_name"),
        }
        enriched = {
            **r,
            "owner": owner_info,
            "player_details": resolve_ids(r.get("players"), players),
        }
        enriched_rosters.append(enriched)
        compact_rosters.append({
            "roster_id": r.get("roster_id"),
            "owner": owner_info,
            "settings": r.get("settings"),
            "players": resolve_ids(r.get("players"), players),
            "starters": resolve_ids(r.get("starters"), players),
            "reserve": resolve_ids(r.get("reserve"), players),
            "taxi": resolve_ids(r.get("taxi"), players),
        })

    draft_details = []
    for d in drafts:
        did = d.get("draft_id")
        picks = []
        if did:
            try:
                picks = get(f"/draft/{did}/picks")
            except Exception as e:
                picks = [{"_error": str(e)}]
        draft_details.append({**d, "picks": picks})

    current_week = int(nfl_state.get("week") or 1)
    max_week = max(18, current_week)
    weekly = {}
    recent_trades = []
    for week in range(1, max_week + 1):
        entry = {}
        try:
            entry["matchups"] = get(f"/league/{LEAGUE_ID}/matchups/{week}")
        except Exception as e:
            entry["matchups_error"] = str(e)
        try:
            txns = get(f"/league/{LEAGUE_ID}/transactions/{week}")
            entry["transactions"] = txns
            for t in txns:
                if t.get("type") == "trade":
                    recent_trades.append({"week": week, **t})
        except Exception as e:
            entry["transactions_error"] = str(e)
        weekly[str(week)] = entry
        time.sleep(0.05)

    my_user = next(
        (u for u in users if u.get("user_id") == account.get("user_id")),
        None,
    )
    my_roster = None
    if my_user:
        uid = my_user.get("user_id")
        my_roster = next(
            (
                r for r in enriched_rosters
                if r.get("owner_id") == uid
                or uid in (r.get("co_owners") or [])
            ),
            None,
        )

    future_picks = build_future_pick_ledger(rosters, traded_picks, league)

    generated_at = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "generated_at": generated_at,
        "league_id": LEAGUE_ID,
        "sleeper_username": USERNAME,
        "nfl_state": nfl_state,
        "sleeper_account": account,
        "league": league,
        "users": users,
        "rosters": enriched_rosters,
        "traded_picks": traded_picks,
        "future_picks_by_roster": future_picks,
        "drafts": draft_details,
        "weekly": weekly,
        "players": players,
        "my_user": my_user,
        "my_roster": my_roster,
    }

    trade_context = {
        "generated_at": generated_at,
        "league": {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "season": league.get("season"),
            "status": league.get("status"),
            "total_rosters": league.get("total_rosters"),
            "roster_positions": league.get("roster_positions"),
            "scoring_settings": league.get("scoring_settings"),
            "settings": league.get("settings"),
        },
        "nfl_state": nfl_state,
        "sleeper_username": USERNAME,
        "sleeper_account": account,
        "my_user": my_user,
        "my_roster": my_roster,
        "rosters": compact_rosters,
        "future_picks_by_roster": future_picks,
        "traded_picks": traded_picks,
        "recent_trades": recent_trades,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "league_snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    (DATA_DIR / "trade_context.json").write_text(
        json.dumps(trade_context, indent=2, sort_keys=True), encoding="utf-8"
    )
    (DATA_DIR / "my_roster.json").write_text(
        json.dumps({
            "generated_at": generated_at,
            "league_id": LEAGUE_ID,
            "username": USERNAME,
            "account": account,
            "user": my_user,
            "roster": my_roster,
            "future_picks": future_picks.get(str((my_roster or {}).get("roster_id")), []),
        }, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(
        f"Wrote Sleeper data: {len(enriched_rosters)} rosters, "
        f"{len(players)} rostered players, {len(recent_trades)} trades"
    )

if __name__ == "__main__":
    main()
