import json
import time

import requests

home_token = "home_token here"
token = "production_token here"
cur_time = int(str(time.time()).replace(".", ""))
clantag = "clan_tag"
headers = {"Authorization": "Bearer " + token}
url_clan = "https://api.clashofclans.com/v1/clans/%23" + clantag[1:]
players = []
all_info = {}
out_all = "../json_data/clan-info.json"
out_clan = "../json_data/clan-info-clan.json"
out_players = "../json_data/clan-info-players.json"
r = requests.get(url_clan, headers=headers)
if r.ok:
    json_clan = json.loads(r.text)
updated_line = {"updatedOn": cur_time}
clan_line = {"clan": json_clan}
all_info.update(clan_line)
for player in json_clan["memberList"]:
    player_tag = player["tag"]
    url_player = "https://api.clashofclans.com/v1/players/%23" + player_tag[1:]
    rp = requests.get(url_player, headers=headers)
    if rp.ok:
        json_player = json.loads(rp.text)
        players.append(json_player)
player_line = {"players": players}
all_info.update(player_line)
with open(out_all, "w") as fw_all:
    fw_all.write(json.dumps(all_info))
    fw_all.close()
with open(out_clan, "w") as fw_clan:
    fw_clan.write(json.dumps(json_clan))
    fw_clan.close()
with open(out_players, "w") as fw_players:
    fw_players.write(json.dumps(players))
    fw_players.close()
