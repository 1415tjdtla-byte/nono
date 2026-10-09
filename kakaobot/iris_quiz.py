"""파이트 퀴즈 카톡봇 (Iris + irispy-client)

실행:  python iris_quiz.py 127.0.0.1:3000
       (인자 대신 IRIS_URL 환경변수로 줘도 됩니다)

명령어
  !퀴즈 / !퀴즈 ufc / !퀴즈 로드 / !퀴즈 상식   문제 출제
  1~4 또는 보기 글자                          정답 제출 (문제당 한 사람 한 번)
  !힌트   오답 보기 하나 지우기
  !포기   정답 공개
  !순위   이 방 점수 순위
  !퀴즈도움말
"""
import json
import os
import random
import sys
import threading
from pathlib import Path

from iris import Bot, ChatContext

BASE = Path(__file__).resolve().parent
QUESTIONS = json.loads((BASE / "questions.json").read_text(encoding="utf-8"))
SCORE_FILE = BASE / "scores.json"

CATS = {
    "ufc": "UFC", "유에프씨": "UFC",
    "로드": "ROAD FC", "로드fc": "ROAD FC", "roadfc": "ROAD FC", "road": "ROAD FC",
    "상식": "상식",
}
CAT_NAME = {"UFC": "UFC", "ROAD FC": "로드FC", "상식": "격투기 상식"}
NUM = ["1", "2", "3", "4"]

HELP = "\n".join([
    f"🥊 파이트 퀴즈 봇 (총 {len(QUESTIONS)}문제)",
    "",
    "!퀴즈 : 전체에서 출제",
    "!퀴즈 ufc / !퀴즈 로드 / !퀴즈 상식",
    "1~4 : 정답 제출 (문제당 1인 1회)",
    "!힌트 : 오답 하나 지우기",
    "!포기 : 정답 공개",
    "!순위 : 이 방 점수 순위",
])

lock = threading.Lock()  # Iris 이벤트는 여러 스레드에서 동시에 들어옴
games = {}    # room_id -> {"x": 문제, "tried": set(user_id), "hidden": [보기 번호]}
recent = {}   # room_id -> 최근 낸 문제 번호 (중복 방지)


def load_scores():
    try:
        return json.loads(SCORE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


scores = load_scores()  # room_id -> {user_id: {"name": 이름, "score": 점수}}


def save_scores():
    tmp = SCORE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(scores, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SCORE_FILE)


def pick(room, cat):
    pool = [i for i, q in enumerate(QUESTIONS) if cat is None or q["c"] == cat]
    seen = recent.get(room, [])
    fresh = [i for i in pool if i not in seen] or pool
    n = random.choice(fresh)
    seen = (seen if fresh is not pool else []) + [n]
    recent[room] = seen[-int(len(pool) * 0.7):]
    src = QUESTIONS[n]
    order = random.sample(range(4), 4)
    return {
        "c": src["c"], "q": src["q"], "e": src["e"],
        "o": [src["o"][k] for k in order],
        "a": order.index(src["a"]),
    }


def question_text(x, hidden):
    lines = [f"🥊 [{CAT_NAME[x['c']]}] {x['q']}", ""]
    for i in range(4):
        lines.append(f"{NUM[i]}. {'(삭제됨)' if i in hidden else x['o'][i]}")
    lines += ["", "번호로 답하세요! (!힌트 / !포기)"]
    return "\n".join(lines)


def ranking(room):
    s = scores.get(room)
    if not s:
        return "아직 점수가 없어요. !퀴즈 로 시작하세요!"
    top = sorted(s.values(), key=lambda p: -p["score"])[:10]
    medal = ["🥇", "🥈", "🥉"]
    return "🏆 퀴즈 순위\n\n" + "\n".join(
        f"{medal[i] if i < 3 else f'{i + 1}.'} {p['name']} - {p['score']}점"
        for i, p in enumerate(top)
    )


def handle(room, user_id, name, msg):
    """메시지 하나를 처리하고 보낼 답장(없으면 None)을 돌려준다."""
    msg = msg.strip()
    game = games.get(room)

    if msg in ("!퀴즈도움말", "!퀴즈 도움말"):
        return HELP

    if msg == "!퀴즈" or msg.startswith("!퀴즈 "):
        if game:
            return "아직 푸는 중인 문제가 있어요!\n\n" + question_text(game["x"], game["hidden"])
        arg = msg[3:].replace(" ", "").lower()
        cat = None
        if arg:
            cat = CATS.get(arg)
            if cat is None:
                return "카테고리는 ufc, 로드, 상식 중에 골라주세요."
        x = pick(room, cat)
        games[room] = {"x": x, "tried": set(), "hidden": []}
        return question_text(x, [])

    if msg == "!순위":
        return ranking(room)

    if not game:
        return None
    x = game["x"]

    if msg == "!포기":
        del games[room]
        return f"정답은 {NUM[x['a']]}. {x['o'][x['a']]}\n\n💡 {x['e']}\n\n다음 문제: !퀴즈"

    if msg == "!힌트":
        wrong = [i for i in range(4) if i != x["a"] and i not in game["hidden"]]
        if len(wrong) <= 1:
            return "더 이상 지울 보기가 없어요!"
        game["hidden"].append(random.choice(wrong))
        return question_text(x, game["hidden"])

    if msg in NUM:
        choice = NUM.index(msg)
    elif msg in x["o"]:
        choice = x["o"].index(msg)
    else:
        return None
    if choice in game["hidden"]:
        return None

    if user_id in game["tried"]:
        return f"{name}님은 이미 답을 냈어요!"
    game["tried"].add(user_id)

    if choice != x["a"]:
        return f"❌ 땡! {name}님 오답"

    del games[room]
    p = scores.setdefault(room, {}).setdefault(user_id, {"name": name, "score": 0})
    p["name"] = name
    p["score"] += 1
    save_scores()
    return (f"⭕ 정답! {name}님 +1점 (총 {p['score']}점)\n\n"
            f"{NUM[x['a']]}. {x['o'][x['a']]}\n💡 {x['e']}\n\n다음 문제: !퀴즈")


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("IRIS_URL", "127.0.0.1:3000")
    bot = Bot(url)

    @bot.on_event("message")
    def on_message(chat: ChatContext):
        with lock:
            reply = handle(str(chat.room.id), str(chat.sender.id),
                           chat.sender.name or "익명", chat.message.msg)
        if reply:
            chat.reply(reply)

    bot.run()


if __name__ == "__main__":
    main()
