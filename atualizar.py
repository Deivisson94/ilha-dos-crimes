from datetime import datetime
import json
import os
import time
import urllib.parse
import requests
import re

API_KEY = "RGAPI-e5ed2ab3-90a3-4367-9402-8f24b8db8c55"

summoners = [
    {"id": "1", "name": "IDC BABY", "tag": "BABY"},
    {"id": "2", "name": "sailor mars", "tag": "408"},
    {"id": "3", "name": "IDC Malvadeza", "tag": "BR1"},
    {"id": "4", "name": "IDC PaiPelado", "tag": "BR1"},
    {"id": "5", "name": "IDC yOKA", "tag": "pnl"},
    {"id": "6", "name": "IDC Ruan", "tag": "br1"},
    {"id": "7", "name": "ADogC", "tag": "br1"},
    {"id": "8", "name": "DLS ADogC", "tag": "DLS"},
]

headers = {"X-Riot-Token": API_KEY}
updated_data = []

tier_weights = {
    "CHALLENGER": 10000, "GRANDMASTER": 9000, "MASTER": 8000,
    "DIAMOND": 7000, "EMERALD": 6000, "PLATINUM": 5000,
    "GOLD": 4000, "SILVER": 3000, "BRONZE": 2000, "IRON": 1000, "UNRANKED": 0
}
div_weights = {"I": 400, "II": 300, "III": 200, "IV": 100}

try:
  versions = requests.get("https://ddragon.leagueoflegends.com/api/versions.json").json()
  ddragon_ver = versions[0]
except Exception:
  ddragon_ver = "14.20.1"

print("==================================================")
print("🧠 ILHA DOS CRIMES - EXTRAÇÃO ESTÁVEL")
print("==================================================\n")

for s in summoners:
  print(f"🔍 Buscando dados de: {s['name']} #{s['tag']}")
  encoded_name = urllib.parse.quote(s["name"].strip())
  encoded_tag = urllib.parse.quote(s["tag"].strip())

  solo_data = {"tier": "UNRANKED", "division": "", "lp": 0, "wins": 0, "losses": 0}
  flex_data = {"tier": "UNRANKED", "division": "", "lp": 0, "wins": 0, "losses": 0}
  level, icon_id = 1, 29

  try:
    acc_url = f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{encoded_name}/{encoded_tag}"
    res_acc = requests.get(acc_url, headers=headers, timeout=10)
    time.sleep(0.7)

    if res_acc.status_code == 200:
      puuid = res_acc.json().get("puuid")
      sum_url = f"https://br1.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
      res_sum = requests.get(sum_url, headers=headers, timeout=10)
      time.sleep(0.7)

      if res_sum.status_code == 200:
        sum_data = res_sum.json()
        level = sum_data.get("summonerLevel", 1)
        icon_id = sum_data.get("profileIconId", 29)
        summoner_id = sum_data.get("id")

        league_url = f"https://br1.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
        res_league = requests.get(league_url, headers=headers, timeout=10)
        time.sleep(0.7)
        if res_league.status_code == 200:
          for l in res_league.json():
            q = l.get("queueType")
            if q == "RANKED_SOLO_5x5":
              solo_data = {
                  "tier": l.get("tier", "UNRANKED"),
                  "division": l.get("rank", ""),
                  "lp": l.get("leaguePoints", 0),
                  "wins": l.get("wins", 0),
                  "losses": l.get("losses", 0),
              }
            elif q == "RANKED_FLEX_SR":
              flex_data = {
                  "tier": l.get("tier", "UNRANKED"),
                  "division": l.get("rank", ""),
                  "lp": l.get("leaguePoints", 0),
                  "wins": l.get("wins", 0),
                  "losses": l.get("losses", 0),
              }
  except Exception as e:
    print(f"  ❌ Erro: {e}")

  t_weight = tier_weights.get(solo_data["tier"], 0)
  d_weight = div_weights.get(solo_data["division"], 0)
  score = t_weight + d_weight + solo_data["lp"]

  player_info = {
      "id": s["id"],
      "gameName": s["name"],
      "tagLine": s["tag"],
      "level": level,
      "ddragonVer": ddragon_ver,
      "iconUrl": f"https://ddragon.leagueoflegends.com/cdn/{ddragon_ver}/img/profileicon/{icon_id}.png",
      "solo": solo_data,
      "flex": flex_data,
      "score": score,
  }
  updated_data.append(player_info)

updated_data.sort(key=lambda x: x["score"], reverse=True)

try:
  with open("index.html", "r", encoding="utf-8") as f:
    html_content = f.read()

  json_str = json.dumps(updated_data, ensure_ascii=False, indent=2)
  new_html = re.sub(
      r"const summoners = \[.*?\];",
      f"const summoners = {json_str};",
      html_content,
      flags=re.DOTALL,
  )

  with open("index.html", "w", encoding="utf-8") as f:
    f.write(new_html)

  print("\n==================================================")
  print("✅ SUCESSO! DADOS ESTÁVEIS ATUALIZADOS")
  print("==================================================")
except Exception as e:
  print(f"\n❌ Erro ao salvar index.html: {e}")