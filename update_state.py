import csv, json, re, time
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
STATE = BASE / "state.json"
CHANNELS = ["radarrussiia", "kupolrussia", "locatorru"]
TTL = 45 * 60 * 1000
SMOKE_TTL = 15 * 60 * 1000
P = {"missile": 3, "uav": 2, "balloon": 1}
ACTIVE = (r"опасност|тревог|угроз|внимани|налет|атак|пуск|летит|летят|"
          r"(?<![а-я])курс(?!к)|направлен|движет|угрожа|взрыв|работает пво|фиксац|активност|ударн")
SUMMARY = r"за ночь|за сутки|за прошедш|итог|всего|над морем|в море|акватор|черн\w* мор|азов\w* мор"
SHOT = r"сбит|сбили|сбита|сбиты|уничтожен|перехват"

REGIONS = []
with open(BASE / "regions.csv", encoding="utf-8") as f:
    for code, name, x, y, *stem in csv.reader(f):
        pat = stem[0] if stem and stem[0] else name.split()[0].lower()[:-2]
        REGIONS.append((code, re.compile(pat)))

def detect(low):
    if re.search(r"отбой|снят|миновал|отмен", low):
        return "clear"
    if re.search(SUMMARY, low):
        return None
    if re.search(SHOT, low):
        return "shot"
    if not re.search(ACTIVE, low):
        return None
    if "ракет" in low:
        return "missile"
    if re.search(r"мвш|воздушн\S* шар", low):
        return "balloon"
    return "uav"

def fetch(ch):
    r = requests.get(f"https://t.me/s/{ch}", timeout=20,
                     headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for m in soup.select(".tgme_widget_message"):
        t = m.select_one(".tgme_widget_message_text")
        tm = m.select_one(".tgme_widget_message_date time")
        post = m.get("data-post")
        if not (t and tm and tm.get("datetime") and post):
            continue
        for br in t.find_all("br"):
            br.replace_with("\n")
        lines = [l for l in t.get_text().splitlines()
                 if "@" not in l and "обход" not in l.lower()]
        ts = datetime.fromisoformat(tm["datetime"]).timestamp()
        out.append((int(post.split("/")[1]), ts, ch, "\n".join(lines).strip()))
    return out

def apply(state, shots, ts, ch, text, now):
    if now - ts * 1000 > TTL:
        return
    for block in re.split(r"\n\s*\n", text):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        low = "\n".join(lines).lower().replace("ё", "е")
        kind = detect(low)
        if not kind:
            continue
        for code, rx in REGIONS:
            if not rx.search(low):
                continue
            if kind == "shot":
                if now - ts * 1000 <= SMOKE_TTL:
                    shots[code] = max(shots.get(code, 0), ts * 1000)
            elif kind == "clear":
                state.pop(code, None)
            else:
                cur = state.get(code)
                if not (cur and cur["p"] > P[kind]):
                    state[code] = {"p": P[kind], "ts": ts * 1000,
                                   "src": "@" + ch, "text": " · ".join(lines)}

def main():
    data = (json.loads(STATE.read_text(encoding="utf-8"))
            if STATE.exists() else {})
    state = data.get("state", {})
    seen = data.get("seen", {})
    shots = data.get("shots", {})
    now = time.time() * 1000

    new = []
    for ch in CHANNELS:
        try:
            for mid, ts, c, text in fetch(ch):
                if mid > seen.get(ch, 0):
                    seen[ch] = mid
                    new.append((ts, c, text))
        except Exception as e:
            print("ошибка", ch, e)

    for ts, c, text in sorted(new):
        apply(state, shots, ts, c, text, now)

    for code in list(state):
        if now - state[code]["ts"] > TTL:
            del state[code]
    for code in list(shots):
        if now - shots[code] > SMOKE_TTL:
            del shots[code]

    STATE.write_text(json.dumps({"updated": int(now), "state": state,
                                 "seen": seen, "shots": shots},
                                ensure_ascii=False), encoding="utf-8")
    print("новых постов:", len(new), "активных регионов:", len(state),
          "дымов:", len(shots))

if __name__ == "__main__":
    main()
