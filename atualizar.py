import os
import sys
import time
import json
import urllib.parse
import requests
import re
from datetime import datetime

try:
  from zoneinfo import ZoneInfo
  TZ_BR = ZoneInfo("America/Sao_Paulo")
except Exception:
  TZ_BR = None

# A chave vem SEMPRE do ambiente (Secret RIOT_API_KEY no GitHub Actions).
# Para rodar localmente, defina a variável de ambiente RIOT_API_KEY.
API_KEY = os.getenv("RIOT_API_KEY", "").strip()
if not API_KEY:
  print("❌ RIOT_API_KEY não definida. Configure o Secret no GitHub "
        "(Settings > Secrets and variables > Actions).")
  sys.exit(1)

# ~1,25s entre chamadas mantém o script abaixo do limite de 100 req / 2 min
# da chave de desenvolvimento.
CALL_DELAY = 1.25
AUTH_FAILED = False

summoners = [
    {"id": "1", "name": "IDC BABY", "tag": "BABY"},
    {"id": "2", "name": "sailor mars", "tag": "408"},
    {"id": "3", "name": "IDC Malvadeza", "tag": "BR1"},
    {"id": "4", "name": "IDC PaiPelado", "tag": "BR1"},
    {"id": "5", "name": "IDC yOKA", "tag": "pnl"},
    {"id": "6", "name": "IDC Ruan", "tag": "br1"},
    {"id": "7", "name": "ADogC", "tag": "br1"},
    {"id": "8", "name": "DLS ADogC", "tag": "DLS"},
    {"id": "9", "name": "Não é Bambole", "tag": "br1"},
    {"id": "10", "name": "ThreshHookTorto", "tag": "br1"},
]

headers = {"X-Riot-Token": API_KEY}
updated_data = []

tier_weights = {
    "CHALLENGER": 10000,
    "GRANDMASTER": 9000,
    "MASTER": 8000,
    "DIAMOND": 7000,
    "EMERALD": 6000,
    "PLATINUM": 5000,
    "GOLD": 4000,
    "SILVER": 3000,
    "BRONZE": 2000,
    "IRON": 1000,
    "UNRANKED": 0,
}

div_weights = {"I": 400, "II": 300, "III": 200, "IV": 100}

SUMMONERS_RE = re.compile(r"const summoners = (\[.*?\]);", re.DOTALL)


def riot_get(url, timeout=10):
  """GET na API da Riot com pausa fixa e novas tentativas em caso de 429."""
  global AUTH_FAILED
  res = None
  for _ in range(3):
    res = requests.get(url, headers=headers, timeout=timeout)
    if res.status_code == 429:
      wait = int(res.headers.get("Retry-After", "5")) + 1
      print(f"  ⏳ Limite de requisições (429). Aguardando {wait}s...")
      time.sleep(wait)
      continue
    break
  if res is not None and res.status_code in (401, 403):
    AUTH_FAILED = True
  time.sleep(CALL_DELAY)
  return res


# Dados anteriores (para NÃO apagar o painel se a API falhar numa execução)
previous_by_id = {}
try:
  with open("index.html", "r", encoding="utf-8") as f:
    _m = SUMMONERS_RE.search(f.read())
  if _m:
    previous_by_id = {str(p.get("id")): p for p in json.loads(_m.group(1))}
except Exception as e:
  print(f"⚠️ Não foi possível ler os dados anteriores: {e}")

# Pega SEMPRE a versão mais recente do DataDragon
try:
  versions = requests.get(
      "https://ddragon.leagueoflegends.com/api/versions.json", timeout=10
  ).json()
  ddragon_ver = versions[0]
except Exception:
  ddragon_ver = "14.20.1"

print(f"📦 Usando DataDragon Versão: {ddragon_ver}")

try:
  champ_dict_raw = requests.get(
      f"https://ddragon.leagueoflegends.com/cdn/{ddragon_ver}/data/pt_BR/champion.json",
      timeout=10,
  ).json()["data"]
  champ_id_to_name = {
      int(v["key"]): v["id"] for k, v in champ_dict_raw.items()
  }
except Exception:
  champ_id_to_name = {}


def get_live_game(puuid, champ_map):
  """Verifica se o jogador está em partida ao vivo (Spectator API v5)."""
  url = f"https://br1.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
  try:
    res = riot_get(url, timeout=8)
    # 404 = fora de partida (comportamento normal, não é erro)
    if res.status_code == 200:
      data = res.json()
      length = max(int(data.get("gameLength", 0)), 0)
      participants = []
      for p in data.get("participants", []):
        participants.append({
            "riotId": p.get("riotId") or p.get("summonerName") or "Invocador",
            "champion": champ_map.get(p.get("championId", 0), "Unknown"),
            "teamId": p.get("teamId", 100),
        })
      return {
          "inGame": True,
          "data": {
              "gameId": data.get("gameId"),
              "gameMode": data.get("gameMode", "CLASSIC"),
              "gameType": data.get("gameType", "MATCHED"),
              "queueId": data.get("gameQueueConfigId", 0),
              "gameTimeFormatted": f"{length // 60}m {length % 60:02d}s",
              "participants": participants,
          },
      }
  except Exception as e:
    print(f"  ⚠️ Não foi possível obter partida ao vivo: {e}")
  return {"inGame": False, "data": None}


print("==================================================")
print("🧠 ILHA DOS CRIMES - EXTRAÇÃO OTIMIZADA (SEM RATE LIMIT)")
print("==================================================\n")

players_ok = 0

for s in summoners:
  print("--------------------------------------------------")
  print(f"🔍 Extraindo dados de: {s['name']} #{s['tag']}")

  prev = previous_by_id.get(s["id"], {})
  player_ok = False  # só vira True se conta + invocador responderem 200

  encoded_name = urllib.parse.quote(s["name"].strip())
  encoded_tag = urllib.parse.quote(s["tag"].strip())

  solo_data = prev.get("solo") or {
      "tier": "UNRANKED", "division": "", "lp": 0, "wins": 0, "losses": 0,
  }
  flex_data = prev.get("flex") or {
      "tier": "UNRANKED", "division": "", "lp": 0, "wins": 0, "losses": 0,
  }
  level = prev.get("level", 1)
  icon_id = 29
  prev_icon = prev.get("iconUrl")
  history_list = prev.get("history", [])
  new_history = []
  champ_stats = {}
  mastery_data = prev.get("mastery") or {
      "totalScore": 0,
      "totalPoints": 0,
      "championsCount": 0,
      "totalAvailable": 173,
      "list": [],
  }
  live_game = {"inGame": False, "data": None}
  history_fetched = False

  try:
    acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
    res_acc = riot_get(acc_url)

    if res_acc.status_code == 200:
      puuid = res_acc.json().get("puuid")

      # 0. PARTIDA AO VIVO
      live_game = get_live_game(puuid, champ_id_to_name)
      if live_game["inGame"]:
        print("  🔴 Em partida agora!")

      sum_url = f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
      res_sum = riot_get(sum_url)

      if res_sum.status_code == 200:
        player_ok = True
        sum_data = res_sum.json()
        level = sum_data.get("summonerLevel", 1)
        icon_id = sum_data.get("profileIconId", 29)
        summoner_id = sum_data.get("id")

        # 1. RANKED (por PUUID; o "id" do invocador foi removido pela Riot)
        league_url = f"https://br1.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        res_league = riot_get(league_url)

        if res_league.status_code != 200 and summoner_id:
          league_url = f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
          res_league = riot_get(league_url)

        if res_league.status_code == 200:
          # Resposta válida: zera e preenche (quem não tem ranque fica UNRANKED)
          solo_data = {"tier": "UNRANKED", "division": "", "lp": 0, "wins": 0, "losses": 0}
          flex_data = {"tier": "UNRANKED", "division": "", "lp": 0, "wins": 0, "losses": 0}
          for l in res_league.json():
            q = l.get("queueType")
            entry = {
                "tier": l.get("tier", "UNRANKED"),
                "division": l.get("rank", ""),
                "lp": l.get("leaguePoints", 0),
                "wins": l.get("wins", 0),
                "losses": l.get("losses", 0),
            }
            if q == "RANKED_SOLO_5x5":
              solo_data = entry
            elif q == "RANKED_FLEX_SR":
              flex_data = entry

        # 2. MAESTRIA
        mast_url = f"https://br1.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
        res_mast = riot_get(mast_url)

        if res_mast.status_code == 200:
          m_json = res_mast.json()
          tot_score = sum(item.get("championLevel", 0) for item in m_json)
          tot_pts = sum(item.get("championPoints", 0) for item in m_json)

          m_list = []
          for item in m_json[:16]:
            c_id = item.get("championId")
            c_name = champ_id_to_name.get(c_id, "Lux")
            m_list.append({
                "champion": c_name,
                "level": item.get("championLevel", 1),
                "points": item.get("championPoints", 0),
            })

          mastery_data = {
              "totalScore": tot_score,
              "totalPoints": tot_pts,
              "championsCount": len(m_json),
              "totalAvailable": 173,
              "list": m_list,
          }

      # 3. HISTÓRICO DE PARTIDAS (5 recentes para poupar a API)
      matches_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=5"
      res_matches = riot_get(matches_url)

      if res_matches.status_code == 200:
        history_fetched = True
        match_ids = res_matches.json()

        for m_id in match_ids:
          m_url = f"https://americas.api.riotgames.com/lol/match/v5/matches/{m_id}"
          res_m = riot_get(m_url)

          if res_m.status_code == 200:
            m_data = res_m.json()
            info = m_data.get("info", {})
            creation_time = info.get("gameCreation", 0) / 1000.0
            game_duration = max(info.get("gameDuration", 1), 1)
            duration_min = round(game_duration / 60, 1)
            # Horário de Brasília (o runner do GitHub roda em UTC)
            match_dt = (
                datetime.fromtimestamp(creation_time, TZ_BR)
                if TZ_BR
                else datetime.fromtimestamp(creation_time)
            )
            match_year = str(match_dt.year)

            q_id = info.get("queueId", 420)
            if q_id == 420:
              queue_category = "SOLO"
              q_type = "Ranked Solo"
            elif q_id == 440:
              queue_category = "FLEX"
              q_type = "Ranked Flex"
            elif q_id == 450:
              queue_category = "ARAM"
              q_type = "ARAM"
            else:
              queue_category = "NORMAL"
              q_type = "Normal / Outro"

            blue_team, red_team = [], []
            blue_kills, blue_gold, blue_damage, blue_wards, blue_cs = (
                0, 0, 0, 0, 0,
            )
            red_kills, red_gold, red_damage, red_wards, red_cs = 0, 0, 0, 0, 0
            target_player = None

            for p in info.get("participants", []):
              t_id = p.get("teamId", 100)
              k_val = p.get("kills", 0)
              if t_id == 100:
                blue_kills += k_val
              else:
                red_kills += k_val

            for p in info.get("participants", []):
              p_puuid = p.get("puuid")
              c_name = p.get("championName", "Lux")
              kills, deaths, assists = (
                  p.get("kills", 0),
                  p.get("deaths", 0),
                  p.get("assists", 0),
              )
              damage = p.get("totalDamageDealtToChampions", 0)
              damage_taken = p.get("totalDamageTaken", 0)
              gold = p.get("goldEarned", 0)
              wards = p.get("wardsPlaced", 0)
              cs = p.get("totalMinionsKilled", 0) + p.get(
                  "neutralMinionsKilled", 0
              )
              cs_min = round(cs / duration_min, 1) if duration_min > 0 else 0
              p_win = p.get("win", False)
              team_id = p.get("teamId", 100)
              items = [p.get(f"item{i}", 0) for i in range(7)]

              tot_team_kills = blue_kills if team_id == 100 else red_kills
              p_kill_pct = (
                  round(((kills + assists) / tot_team_kills) * 100)
                  if tot_team_kills > 0
                  else 0
              )
              kda_val = (
                  (kills + assists) / deaths if deaths > 0 else (kills + assists)
              )
              op_score = round(min(10.0, max(2.0, 3.0 + kda_val * 1.2)), 1)

              player_dict = {
                  "name": p.get("riotIdGameName", p.get("summonerName", "P1")),
                  "champion": c_name,
                  "champLevel": p.get("champLevel", 1),
                  "kills": kills,
                  "deaths": deaths,
                  "assists": assists,
                  "pKillPct": p_kill_pct,
                  "damage": damage,
                  "damageTaken": damage_taken,
                  "gold": gold,
                  "wards": wards,
                  "cs": cs,
                  "csMin": cs_min,
                  "items": items,
                  "opScore": op_score,
                  "win": p_win,
                  "teamId": team_id,
                  "isMVP": False,
                  "isACE": False,
              }

              if team_id == 100:
                blue_team.append(player_dict)
                blue_gold += gold
                blue_damage += damage
                blue_wards += wards
                blue_cs += cs
              else:
                red_team.append(player_dict)
                red_gold += gold
                red_damage += damage
                red_wards += wards
                red_cs += cs

              if p_puuid == puuid:
                target_player = player_dict

            if target_player:
              c_name = target_player["champion"]
              if c_name not in champ_stats:
                champ_stats[c_name] = {
                    "champion": c_name,
                    "games": 0,
                    "wins": 0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                    "csTotal": 0,
                    "durationTotal": 0,
                    "damageTotal": 0,
                }
              champ_stats[c_name]["games"] += 1
              if target_player["win"]:
                champ_stats[c_name]["wins"] += 1
              champ_stats[c_name]["kills"] += target_player["kills"]
              champ_stats[c_name]["deaths"] += target_player["deaths"]
              champ_stats[c_name]["assists"] += target_player["assists"]
              champ_stats[c_name]["csTotal"] += target_player["cs"]
              champ_stats[c_name]["durationTotal"] += duration_min
              champ_stats[c_name]["damageTotal"] += target_player["damage"]

              new_history.append({
                  "matchId": m_id,
                  "queueCategory": queue_category,
                  "seasonYear": match_year,
                  "champion": target_player["champion"],
                  "kills": target_player["kills"],
                  "deaths": target_player["deaths"],
                  "assists": target_player["assists"],
                  "pKillPct": target_player["pKillPct"],
                  "win": target_player["win"],
                  "type": q_type,
                  "time": match_dt.strftime("%d/%m %H:%M"),
                  "duration": f"{int(duration_min)}m",
                  "items": target_player["items"],
                  "opScore": target_player["opScore"],
                  "blueTeam": blue_team,
                  "redTeam": red_team,
                  "blueStats": {
                      "kills": blue_kills,
                      "gold": blue_gold,
                      "damage": blue_damage,
                      "wards": blue_wards,
                      "cs": blue_cs,
                  },
                  "redStats": {
                      "kills": red_kills,
                      "gold": red_gold,
                      "damage": red_damage,
                      "wards": red_wards,
                      "cs": red_cs,
                  },
              })
    else:
      print(f"  ⚠️ Conta não encontrada/erro (HTTP {res_acc.status_code}).")
  except Exception as e:
    print(f"  ❌ Erro: {e}")

  # Se a API falhou para este jogador, mantém o que já estava no painel
  if not player_ok:
    if prev:
      print("  ↩️ Mantendo os dados anteriores deste invocador.")
      prev["liveGame"] = {"inGame": False, "data": None}
      updated_data.append(prev)
    continue

  players_ok += 1
  if history_fetched:
    history_list = new_history

  all_champions_list = []
  sorted_champs = sorted(
      champ_stats.values(), key=lambda x: x["games"], reverse=True
  )
  for c in sorted_champs:
    games = c["games"]
    wins = c["wins"]
    losses = games - wins
    wr = round((wins / games) * 100) if games > 0 else 0
    avg_k = round(c["kills"] / games, 1) if games > 0 else 0
    avg_d = round(c["deaths"] / games, 1) if games > 0 else 0
    avg_a = round(c["assists"] / games, 1) if games > 0 else 0
    kda_ratio = (
        round((c["kills"] + c["assists"]) / c["deaths"], 2)
        if c["deaths"] > 0
        else round(c["kills"] + c["assists"], 2)
    )
    avg_cs = round(c["csTotal"] / games, 1) if games > 0 else 0
    avg_cs_min = (
        round(c["csTotal"] / c["durationTotal"], 1)
        if c["durationTotal"] > 0
        else 0
    )

    all_champions_list.append({
        "champion": c["champion"],
        "games": games,
        "wins": wins,
        "losses": losses,
        "winRate": wr,
        "kdaRatio": kda_ratio,
        "avgKDA": f"{avg_k} / {avg_d} / {avg_a}",
        "avgCS": avg_cs,
        "avgCSMin": avg_cs_min,
    })

  # Se o histórico não veio, preserva as estatísticas de campeões anteriores
  if not history_fetched:
    all_champions_list = prev.get("allChampions", [])

  t_weight = tier_weights.get(solo_data["tier"], 0)
  d_weight = div_weights.get(solo_data["division"], 0)
  score = t_weight + d_weight + solo_data["lp"]

  player_info = {
      "id": s["id"],
      "gameName": s["name"],
      "tagLine": s["tag"],
      "level": level,
      "ddragonVer": ddragon_ver,
      "iconUrl": (
          f"https://ddragon.leagueoflegends.com/cdn/{ddragon_ver}/img/profileicon/{icon_id}.png"
      ),
      "solo": solo_data,
      "flex": flex_data,
      "topChampions": all_champions_list[:3],
      "allChampions": all_champions_list,
      "mastery": mastery_data,
      "liveGame": live_game,
      "history": history_list,
      "score": score,
  }
  updated_data.append(player_info)

# Se a chave expirou/é inválida ou nenhum invocador respondeu, NÃO mexe no painel
if AUTH_FAILED or players_ok == 0:
  print("\n❌ A API da Riot recusou a chave ou nenhum invocador respondeu.")
  print("   O index.html NÃO foi alterado. Gere uma nova chave e atualize o Secret RIOT_API_KEY.")
  sys.exit(1)

updated_data.sort(key=lambda x: x.get("score", 0), reverse=True)

try:
  with open("index.html", "r", encoding="utf-8") as f:
    html_content = f.read()

  json_str = json.dumps(updated_data, ensure_ascii=False, indent=2)
  # lambda: evita que o re.sub interprete barras invertidas do JSON
  new_html, n = SUMMONERS_RE.subn(
      lambda m: f"const summoners = {json_str};", html_content, count=1
  )
  if n != 1:
    raise RuntimeError("bloco 'const summoners = [...]' não encontrado no index.html")

  with open("index.html", "w", encoding="utf-8") as f:
    f.write(new_html)

  print("\n==================================================")
  print(f"✅ PAINEL ATUALIZADO COM SUCESSO! ({players_ok}/{len(summoners)} invocadores atualizados)")
  print("==================================================")
except Exception as e:
  print(f"\n❌ Erro ao salvar index.html: {e}")
  sys.exit(1)
