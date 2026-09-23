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
OUT = Path("data/league_snapshot.json")
UA = "Sleeper-Bridge/1.0"

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
        "first_name": p.get("first_name"),
        "last_name": p.get("last_name"),
        "position": p.get("position"),
        "fantasy_positions": p.get("fantasy_positions"),
        "team": p.get("team"),
        "age": p.get("age"),
        "years_exp": p.get("years_exp"),
        "status": p.get("status"),
        "injury_status": p.get("injury_status"),
        "injury_body_part": p.get("injury_body_part"),
        "number": p.get("number"),
        "depth_chart_position": p.get("depth_chart_position"),
        "depth_chart_order": p.get("depth_chart_order"),
        "active": p.get("active"),
    }

def main():
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
    for r in rosters:
        owner = user_by_id.get(r.get("owner_id")) or {}
        enriched_rosters.append({
            **r,
            "owner": {
                "user_id": owner.get("user_id"),
                "username": owner.get("username"),
                "display_name": owner.get("display_name"),
                "team_name": (owner.get("metadata") or {}).get("team_name"),
            },
            "player_details": [players.get(pid) for pid in (r.get("players") or [])],
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
    for week in range(1, max_week + 1):
        entry = {}
        try:
            entry["matchups"] = get(f"/league/{LEAGUE_ID}/matchups/{week}")
        except Exception as e:
            entry["matchups_error"] = str(e)
        try:
            entry["transactions"] = get(f"/league/{LEAGUE_ID}/transactions/{week}")
        except Exception as e:
            entry["transactions_error"] = str(e)
        weekly[str(week)] = entry
        time.sleep(0.05)

    my_user = None
    for u in users:
        if (u.get("username") or "").lower() == USERNAME.lower():
            my_user = u
            break

    my_roster = None
    if my_user:
        my_roster = next((r for r in enriched_rosters if r.get("owner_id") == my_user.get("user_id")), None)

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "league_id": LEAGUE_ID,
        "sleeper_username": USERNAME,
        "nfl_state": nfl_state,
        "league": league,
        "users": users,
        "rosters": enriched_rosters,
        "traded_picks": traded_picks,
        "drafts": draft_details,
        "weekly": weekly,
        "players": players,
        "my_user": my_user,
        "my_roster": my_roster,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {OUT} with {len(enriched_rosters)} rosters and {len(players)} rostered players")

if __name__ == "__main__":
    main()

# This file is intentionally watched by the refresh workflow.
