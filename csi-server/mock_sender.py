#!/usr/bin/env python3
"""
CSI Data Sender — Interactive CLI test tool
Kullanım: python csi_sender.py
Gereksinimler: pip install requests
"""

import time
import json
import random
import string
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    print("❌  'requests' paketi bulunamadı. Kurmak için:\n    pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────
#  Config (değiştirilebilir)
# ─────────────────────────────────────────────
BASE_URL   = "https://proxarsever-test.up.railway.app"
MARKET_ID  = "market-001"
JWT_TOKEN  = ""          # boşsa otomatik /dev/token çeker

STATES     = ["walking", "standing", "interacting", "sitting"]

# ─────────────────────────────────────────────
#  Terminal renk kodları
# ─────────────────────────────────────────────
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    ACCENT = "\033[95m"
    WHITE  = "\033[97m"
    PURPLE = "\033[95m"
    BLUE   = "\033[94m"

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg, color=C.WHITE):
    print(f"{C.DIM}[{ts()}]{C.RESET} {color}{msg}{C.RESET}")

def ok(msg):   log(f"✓  {msg}", C.GREEN)
def err(msg):  log(f"✗  {msg}", C.RED)
def info(msg): log(f"→  {msg}", C.CYAN)
def warn(msg): log(f"⚠  {msg}", C.YELLOW)

def separator(title=""):
    w = 56
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{C.DIM}{'─'*pad} {C.BOLD}{C.PURPLE}{title}{C.RESET}{C.DIM} {'─'*pad}{C.RESET}\n")
    else:
        print(f"\n{C.DIM}{'─'*w}{C.RESET}\n")

# ─────────────────────────────────────────────
#  HTTP helpers
# ─────────────────────────────────────────────
def headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {JWT_TOKEN}",
    }

def post(path, payload=None, params=None):
    try:
        r = requests.post(f"{BASE_URL}{path}", json=payload, params=params, headers=headers(), timeout=10)
        return r
    except requests.exceptions.ConnectionError:
        err(f"Bağlantı hatası: {BASE_URL} erişilemiyor.")
        return None
    except requests.exceptions.Timeout:
        err("Zaman aşımı.")
        return None

def get(path, params=None):
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, headers=headers(), timeout=10)
        return r
    except requests.exceptions.ConnectionError:
        err(f"Bağlantı hatası: {BASE_URL} erişilemiyor.")
        return None
    except requests.exceptions.Timeout:
        err("Zaman aşımı.")
        return None

# ─────────────────────────────────────────────
#  Payload üretici
# ─────────────────────────────────────────────
def random_person(index: int) -> dict:
    return {
        "person_id": f"p{index:03d}",
        "timestamp": time.time(),
        "state": random.choice(STATES),
        "position": {
            "x": round(random.uniform(0, 100), 2),
            "y": round(random.uniform(0, 100), 2),
        },
        "velocity_mgntd": round(random.uniform(0, 2.5), 3),
    }

def build_frame(frame_id: int, person_count: int = None) -> dict:
    count = person_count if person_count is not None else random.randint(1, 8)
    return {
        "market_id": MARKET_ID,
        "frame_id":  frame_id,
        "timestamp": time.time(),
        "people": [random_person(i + 1) for i in range(count)],
    }

# ─────────────────────────────────────────────
#  Test fonksiyonları
# ─────────────────────────────────────────────

def fetch_dev_token():
    global JWT_TOKEN
    separator("DEV TOKEN")
    info(f"POST /dev/token  market_id={MARKET_ID}")
    r = post("/dev/token", params={"market_id": MARKET_ID})
    if r is None:
        return False
    if r.status_code == 200:
        data = r.json()
        JWT_TOKEN = data["token"]
        ok(f"Token alındı:")
        print(f"  {C.DIM}{JWT_TOKEN[:60]}...{C.RESET}")
        warn(data.get("warning", ""))
        return True
    else:
        err(f"HTTP {r.status_code} — {r.text}")
        return False


def health_check():
    separator("HEALTH CHECK")
    info("GET /health")
    r = get("/health")
    if r is None:
        return
    if r.ok:
        ok(f"HTTP {r.status_code} — {json.dumps(r.json())}")
    else:
        err(f"HTTP {r.status_code} — {r.text}")


def send_single_frame(frame_id: int = 1, person_count: int = None):
    separator("SINGLE INGEST")
    payload = build_frame(frame_id, person_count)
    info(f"POST /ingest  frame_id={frame_id}  people={len(payload['people'])}")
    print(f"  {C.DIM}{json.dumps(payload, indent=2)}{C.RESET}")
    r = post("/ingest", payload)
    if r is None:
        return
    if r.ok:
        ok(f"HTTP {r.status_code} — {r.json()}")
    else:
        err(f"HTTP {r.status_code} — {r.text}")


def auto_sender(total_frames: int = 10, interval_sec: float = 1.0):
    separator("AUTO SENDER")
    info(f"{total_frames} frame gönderilecek, aralık: {interval_sec}s")
    info("Durdurmak için Ctrl+C\n")

    sent = ok_count = err_count = 0
    start = time.time()

    try:
        for i in range(1, total_frames + 1):
            payload = build_frame(i)
            r = post("/ingest", payload)
            sent += 1
            if r and r.ok:
                ok_count += 1
                resp = r.json()
                print(f"  {C.GREEN}✓{C.RESET} frame={i:04d}  "
                      f"people={len(payload['people'])}  "
                      f"{C.DIM}inserted={resp.get('inserted_people', '?')}{C.RESET}")
            else:
                err_count += 1
                code = r.status_code if r else "—"
                print(f"  {C.RED}✗{C.RESET} frame={i:04d}  HTTP {code}")

            if i < total_frames:
                time.sleep(interval_sec)

    except KeyboardInterrupt:
        warn("\nKullanıcı tarafından durduruldu.")

    elapsed = round(time.time() - start, 2)
    separator()
    print(f"  Gönderilen : {C.WHITE}{sent}{C.RESET}")
    print(f"  Başarılı   : {C.GREEN}{ok_count}{C.RESET}")
    print(f"  Hatalı     : {C.RED}{err_count}{C.RESET}")
    print(f"  Süre       : {C.DIM}{elapsed}s{C.RESET}")


def get_stats():
    separator("MARKET STATS")
    info(f"GET /markets/{MARKET_ID}/stats")
    r = get(f"/markets/{MARKET_ID}/stats")
    if r is None:
        return
    if r.ok:
        data = r.json()
        ok(f"HTTP {r.status_code}")
        for k, v in data.items():
            val = round(v, 4) if isinstance(v, float) else v
            print(f"  {C.DIM}{k:<20}{C.RESET}{C.WHITE}{val}{C.RESET}")
    else:
        err(f"HTTP {r.status_code} — {r.text}")


def get_frame(frame_id: int):
    separator(f"FRAME DETAIL  #{frame_id}")
    info(f"GET /markets/{MARKET_ID}/frames/{frame_id}")
    r = get(f"/markets/{MARKET_ID}/frames/{frame_id}")
    if r is None:
        return
    if r.ok:
        data = r.json()
        ok(f"HTTP {r.status_code}")
        people = data.pop("people", [])
        for k, v in data.items():
            print(f"  {C.DIM}{k:<20}{C.RESET}{C.WHITE}{v}{C.RESET}")
        print(f"\n  {C.CYAN}People ({len(people)}):{C.RESET}")
        for p in people:
            print(f"    {C.DIM}{p}{C.RESET}")
    else:
        err(f"HTTP {r.status_code} — {r.text}")


def list_frames(limit: int = 10):
    separator("FRAME LIST")
    info(f"GET /markets/{MARKET_ID}/frames?limit={limit}")
    r = get(f"/markets/{MARKET_ID}/frames", params={"limit": limit})
    if r is None:
        return
    if r.ok:
        data = r.json()
        ok(f"HTTP {r.status_code}")
        frames = data.get("frames", [])
        if not frames:
            warn("Henüz frame yok.")
            return
        print(f"\n  {'frame_id':<12}{'timestamp':<22}{'person_count'}")
        print(f"  {C.DIM}{'─'*48}{C.RESET}")
        for f in frames:
            ts_fmt = datetime.fromtimestamp(f['timestamp']).strftime("%Y-%m-%d %H:%M:%S") if f.get('timestamp') else '—'
            print(f"  {C.WHITE}{f['frame_id']:<12}{C.RESET}{C.DIM}{ts_fmt:<22}{C.RESET}{f['person_count']}")
    else:
        err(f"HTTP {r.status_code} — {r.text}")


def run_full_test():
    """Tüm endpoint'leri sırayla test eder."""
    separator("FULL TEST SUITE")
    print(f"  {C.CYAN}Base URL  :{C.RESET} {BASE_URL}")
    print(f"  {C.CYAN}Market ID :{C.RESET} {MARKET_ID}")

    # 1. Token
    if not JWT_TOKEN:
        if not fetch_dev_token():
            err("Token alınamadı, test durduruluyor.")
            return
    else:
        info("Mevcut token kullanılıyor.")

    # 2. Health
    health_check()

    # 3. Tek frame ingest
    send_single_frame(frame_id=1, person_count=3)

    # 4. 5 frame auto
    auto_sender(total_frames=5, interval_sec=0.5)

    # 5. Stats
    get_stats()

    # 6. Frame list
    list_frames(limit=5)

    # 7. Frame detail
    get_frame(frame_id=1)

    separator("TAMAMLANDI")
    ok("Full test suite bitti.")


# ─────────────────────────────────────────────
#  Menü
# ─────────────────────────────────────────────

def menu():
    global BASE_URL, MARKET_ID, JWT_TOKEN

    # Başlangıçta token yoksa otomatik çek
    if not JWT_TOKEN:
        info("JWT token yok, /dev/token çekiliyor...")
        fetch_dev_token()

    while True:
        separator("MENÜ")
        print(f"  {C.DIM}URL    :{C.RESET} {BASE_URL}")
        print(f"  {C.DIM}Market :{C.RESET} {MARKET_ID}")
        print(f"  {C.DIM}Token  :{C.RESET} {'✓ set' if JWT_TOKEN else '✗ yok'}\n")

        options = [
            ("1", "Health check"),
            ("2", "Dev token al"),
            ("3", "Tek frame gönder"),
            ("4", "Auto sender (ayarlanabilir)"),
            ("5", "Market stats"),
            ("6", "Frame listesi"),
            ("7", "Frame detayı"),
            ("8", "Full test suite (hepsini çalıştır)"),
            ("9", "Ayarları değiştir"),
            ("0", "Çıkış"),
        ]
        for key, label in options:
            print(f"  {C.ACCENT if key == '8' else C.CYAN}[{key}]{C.RESET}  {label}")
        print()

        choice = input(f"  {C.WHITE}Seçim: {C.RESET}").strip()

        if choice == "1":
            health_check()

        elif choice == "2":
            fetch_dev_token()

        elif choice == "3":
            try:
                fid = int(input("  Frame ID [1]: ").strip() or "1")
                cnt = input("  Kişi sayısı [random]: ").strip()
                cnt = int(cnt) if cnt else None
            except ValueError:
                warn("Geçersiz giriş, varsayılan kullanılıyor.")
                fid, cnt = 1, None
            send_single_frame(fid, cnt)

        elif choice == "4":
            try:
                n   = int(input("  Kaç frame? [20]: ").strip() or "20")
                ivl = float(input("  Aralık saniye? [1.0]: ").strip() or "1.0")
            except ValueError:
                warn("Geçersiz giriş.")
                n, ivl = 20, 1.0
            auto_sender(n, ivl)

        elif choice == "5":
            get_stats()

        elif choice == "6":
            try:
                lim = int(input("  Kaç frame listelesin? [10]: ").strip() or "10")
            except ValueError:
                lim = 10
            list_frames(lim)

        elif choice == "7":
            try:
                fid = int(input("  Frame ID: ").strip() or "1")
            except ValueError:
                fid = 1
            get_frame(fid)

        elif choice == "8":
            run_full_test()

        elif choice == "9":
            separator("AYARLAR")
            new_url = input(f"  Base URL [{BASE_URL}]: ").strip()
            if new_url:
                BASE_URL = new_url
            new_mid = input(f"  Market ID [{MARKET_ID}]: ").strip()
            if new_mid:
                MARKET_ID = new_mid
            new_tok = input(f"  JWT Token [mevcut]: ").strip()
            if new_tok:
                JWT_TOKEN = new_tok
            ok("Ayarlar güncellendi.")

        elif choice == "0":
            print(f"\n{C.DIM}Güle güle.{C.RESET}\n")
            sys.exit(0)

        else:
            warn("Geçersiz seçim.")

        input(f"\n  {C.DIM}Devam için Enter...{C.RESET}")


if __name__ == "__main__":
    print(f"""
{C.PURPLE}{C.BOLD}
  ██████╗███████╗██╗    ███████╗███████╗███╗   ██╗██████╗ ███████╗██████╗
 ██╔════╝██╔════╝██║    ██╔════╝██╔════╝████╗  ██║██╔══██╗██╔════╝██╔══██╗
 ██║     ███████╗██║    ███████╗█████╗  ██╔██╗ ██║██║  ██║█████╗  ██████╔╝
 ██║     ╚════██║██║    ╚════██║██╔══╝  ██║╚██╗██║██║  ██║██╔══╝  ██╔══██╗
 ╚██████╗███████║██║    ███████║███████╗██║ ╚████║██████╔╝███████╗██║  ██║
  ╚═════╝╚══════╝╚═╝    ╚══════╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═╝  ╚═╝
{C.RESET}  {C.DIM}WiFi CSI Heatmap — API Test Tool{C.RESET}
""")
    menu()