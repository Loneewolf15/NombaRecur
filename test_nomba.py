import httpx
import json

base_urls = ["https://sandbox.nomba.com", "https://api.nomba.com", "https://api.sandbox.nomba.com"]
account_ids = ["1866ef9b-880c-4753-85ce-acb505b28023", "760f3870-9a3d-463f-b53f-a5df8b4f64c3"]
client_id = "706df5c4-b0bb-4333-80c4-d23b352f8631"
client_secret = "k8JoG1VSAHj20ceUnNLTVuuxzw1wH4LuXlydJdHsERHOYiS8B4OlVqJauaG+U8fWL1u0YZ9S/mNX+JsQDdM/Pw=="

for url in base_urls:
    for acc in account_ids:
        print(f"Testing {url} with acc {acc}")
        try:
            res = httpx.post(
                f"{url}/v1/auth/token/issue",
                headers={"accountId": acc, "Content-Type": "application/json"},
                json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
            )
            print(res.status_code, res.text)
        except Exception as e:
            print("Error:", e)
