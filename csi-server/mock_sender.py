# mock_sender.py — junk data üretici
import httpx, time, random, math

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJtYXJrZXRfaWQiOiJta3RfdGVzdCIsInN1YiI6Im1rdF90ZXN0In0.E0joSZ8nyXzT9Q0Xkx3I2ieqhnzUFwvkACQw2Awy6fQ"
BASE  = "http://localhost:8000"

def fake_frame(frame_id: int):
    n = random.randint(0, 5)
    return {
        "market_id": "mkt_test",
        "frame_id": frame_id,
        "timestamp": time.time(),
        "people": [
            {
                "person_id": f"p_{i}",
                "timestamp": time.time(),
                "state": random.choice(["MOVING", "STATIONARY", "UNKNOWN"]),
                "position": {
                    "x": round(random.uniform(0, 10), 2),
                    "y": round(random.uniform(0, 10), 2)
                },
                "velocity_mgntd": round(random.uniform(0, 2), 3)
            }
            for i in range(n)
        ]
    }

for i in range(100):
    r = httpx.post(
        f"{BASE}/ingest",
        json=fake_frame(i),
        headers={"Authorization": f"Bearer {TOKEN}"}
    )
    print(f"Frame {i}: {r.status_code}")
    time.sleep(0.1)