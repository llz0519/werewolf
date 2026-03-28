"""
快速集成测试：模拟一局游戏从创建到第一轮完整流程
运行前确保 uvicorn 已在 8000 端口启动
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import requests

BASE = "http://127.0.0.1:8000"

def h(player_id: str) -> dict:
    """构造 player_id Header"""
    return {"player-id": player_id}

def check(resp, label=""):
    if resp.status_code >= 400:
        print(f"  ❌ {label} [{resp.status_code}] {resp.text}")
    else:
        print(f"  ✅ {label} {resp.json()}")
    return resp.json()

print("\n" + "═"*55)
print("① 创建房间（房主 = owner）")
r = requests.post(f"{BASE}/game/create", headers=h("owner"))
data = check(r, "create")
room_id = data["room_id"]

print("\n② 6 名玩家加入")
players = [
    ("owner", "Alice", False),
    ("p2",    "Bob",   True),
    ("p3",    "Charlie", True),
    ("p4",    "Diana",   True),
    ("p5",    "Eve",     True),
    ("p6",    "Frank",   True),
]
for pid, name, is_ai in players:
    r = requests.post(
        f"{BASE}/game/{room_id}/join",
        json={"name": name, "is_ai": is_ai},
        headers=h(pid),
    )
    check(r, f"join {name}")

print("\n③ 房主开始游戏（随机发牌）")
r = requests.post(f"{BASE}/game/{room_id}/start", headers=h("owner"))
check(r, "start")

print("\n④ 用 owner 视角拉取状态（只能看到自己的角色）")
r = requests.get(f"{BASE}/game/{room_id}/state", headers=h("owner"))
state = check(r, "state(owner)")
my_role = state["players"]["owner"]["role"]
print(f"   owner 的角色是：{my_role}")

# 用服务端视角找到各角色（测试专用，正常游戏不会这样做）
# 我们直接多次请求不同 player_id 来找到各角色
print("\n⑤ 找出各角色（逐一查看自己角色）")
role_map = {}
for pid, name, _ in players:
    r = requests.get(f"{BASE}/game/{room_id}/state", headers=h(pid))
    s = r.json()
    role = s["players"][pid]["role"]
    role_map[pid] = role
    print(f"   {name}({pid}) → {role}")

wolves  = [pid for pid, role in role_map.items() if role == "werewolf"]
seer    = next((pid for pid, role in role_map.items() if role == "seer"),   None)
witch   = next((pid for pid, role in role_map.items() if role == "witch"),  None)
villagers = [pid for pid, role in role_map.items() if role == "villager"]

# 验证狼人视角能看到队友
print(f"\n⑥ 狼人视角验证（{wolves[0]} 应能看到 {wolves[1]} 的角色）")
r = requests.get(f"{BASE}/game/{room_id}/state", headers=h(wolves[0]))
s = r.json()
wolf_sees_teammate = s["players"][wolves[1]]["role"]
print(f"   狼人 {wolves[0]} 看到 {wolves[1]} 的角色：{wolf_sees_teammate}  "
      f"{'✅ 正确' if wolf_sees_teammate == 'werewolf' else '❌ 泄漏异常'}")

# 验证村民视角看不到狼人角色
if villagers:
    print(f"\n⑦ 村民视角验证（{villagers[0]} 不应看到狼人角色）")
    r = requests.get(f"{BASE}/game/{room_id}/state", headers=h(villagers[0]))
    s = r.json()
    villager_sees_wolf = s["players"][wolves[0]]["role"]
    print(f"   村民 {villagers[0]} 看到 {wolves[0]} 的角色：{villager_sees_wolf}  "
          f"{'✅ 正确（隐藏）' if villager_sees_wolf is None else '❌ 信息泄漏！'}")

print("\n⑧ 夜晚 - 狼人队内交流后击杀")
for wid in wolves:
    r = requests.post(
        f"{BASE}/game/{room_id}/action/wolf_whisper",
        json={"message": "先刀这个。"},
        headers=h(wid),
    )
    check(r, f"wolf_whisper({wid})")

kill_target = villagers[0] if villagers else seer
r = requests.post(
    f"{BASE}/game/{room_id}/action/wolf_kill",
    json={"target_id": kill_target},
    headers=h(wolves[0]),
)
check(r, f"wolf_kill → {kill_target}")

print("\n⑨ 夜晚 - 预言家查验（查第一只狼）")
if seer:
    r = requests.get(f"{BASE}/game/{room_id}/state", headers=h(seer))
    phase = r.json()["phase"]
    if phase == "night_seer":
        r = requests.post(
            f"{BASE}/game/{room_id}/action/seer_check",
            json={"target_id": wolves[0]},
            headers=h(seer),
        )
        res = check(r, f"seer_check → {wolves[0]}")
        print(f"   查验结果 is_werewolf = {res.get('is_werewolf')}  "
              f"{'✅' if res.get('is_werewolf') else '❌'}")
    else:
        print(f"   预言家阶段被跳过（phase={phase}）")

print("\n⑩ 夜晚 - 女巫不用药")
if witch:
    r = requests.get(f"{BASE}/game/{room_id}/state", headers=h(witch))
    phase = r.json()["phase"]
    if phase == "night_witch":
        r = requests.post(
            f"{BASE}/game/{room_id}/action/witch",
            json={"save": False, "poison_target_id": None},
            headers=h(witch),
        )
        check(r, "witch pass")
    else:
        print(f"   女巫阶段被跳过（phase={phase}）")

print("\n⑪ 白天 - 查看死亡公告后发言")
r = requests.get(f"{BASE}/game/{room_id}/state", headers=h("owner"))
s = r.json()
print(f"   当前阶段：{s['phase']}")
alive_pids = [pid for pid, p in s["players"].items() if p["is_alive"]]
for pid in alive_pids[:3]:
    r = requests.post(
        f"{BASE}/game/{room_id}/action/speak",
        json={"content": f"我是 {pid}，我觉得大家要认真分析。"},
        headers=h(pid),
    )
    check(r, f"speak({pid})")

print("\n⑫ 进入投票阶段")
r = requests.post(f"{BASE}/game/{room_id}/action/next_phase", headers=h("owner"))
check(r, "next_phase → vote")

print("\n⑬ 所有存活玩家投票放逐第一只狼")
for pid in alive_pids:
    if pid != wolves[0]:
        r = requests.post(
            f"{BASE}/game/{room_id}/action/vote",
            json={"target_id": wolves[0]},
            headers=h(pid),
        )
        check(r, f"vote({pid}→{wolves[0]})")

print("\n⑭ 结算投票")
r = requests.post(f"{BASE}/game/{room_id}/action/next_phase", headers=h("owner"))
check(r, "next_phase → result")

print("\n⑮ 推进到第 2 夜")
r = requests.get(f"{BASE}/game/{room_id}/state", headers=h("owner"))
if r.json()["phase"] != "game_over":
    r = requests.post(f"{BASE}/game/{room_id}/action/next_phase", headers=h("owner"))
    check(r, "next_phase → night2")
else:
    print("   游戏已在投票后结束（狼人全灭）✅")

print("\n" + "═"*55)
print("集成测试完成")
