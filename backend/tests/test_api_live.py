"""Quick live API test — run with: python tests/test_api_live.py"""

import httpx

base = "http://localhost:8000/api/meetings"


def main():
    r = httpx.post(base, json={"name": "Live Test Meeting", "mode": "interview"})
    print(f"CREATE: {r.status_code}")
    mid = r.json()["id"]
    print(f"  id = {mid}")

    r = httpx.get(base)
    print(f"LIST:   {r.status_code} -> {len(r.json())} meetings")

    r = httpx.get(f"{base}/{mid}")
    print(f"GET:    {r.status_code} -> {r.json()['name']}")

    r = httpx.patch(f"{base}/{mid}", json={"name": "Updated Name"})
    print(f"PATCH:  {r.status_code} -> {r.json()['name']}")

    r = httpx.delete(f"{base}/{mid}")
    print(f"DELETE: {r.status_code}")

    r = httpx.get(f"{base}/{mid}")
    print(f"GET deleted: {r.status_code} (expect 404)")

    print("\nAll CRUD operations OK!")


if __name__ == "__main__":
    main()
