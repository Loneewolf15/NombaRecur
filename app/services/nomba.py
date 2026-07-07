from datetime import datetime, timedelta
from dateutil import parser
import httpx
from sqlmodel import Session
from app.models.tenant import Tenant
from app.utils.crypto import decrypt_val, encrypt_val
import logging
import uuid

logger = logging.getLogger(__name__)

class NombaAPIError(Exception):
    def __init__(self, code: str, description: str):
        self.code = code
        self.description = description
        super().__init__(f"[{code}] {description}")


class NombaClient:
    """Client for interacting with Nomba API on behalf of a specific tenant."""

    def __init__(self, tenant: Tenant, session: Session):
        self.tenant = tenant
        self.session = session
        # Parent account ID — used in `accountId` header on every request
        self.account_id = decrypt_val(tenant.nomba_account_id_enc)
        # Sub-account ID — scopes transactions; sent as a separate header when present
        self.sub_account_id = decrypt_val(tenant.nomba_sub_account_id_enc) if tenant.nomba_sub_account_id_enc else None

    @property
    def _auth_url(self) -> str:
        return f"{self.tenant.nomba_base_url}/v1/auth/token/issue"

    @property
    def _refresh_url(self) -> str:
        return f"{self.tenant.nomba_base_url}/v1/auth/token/refresh"

    async def get_valid_token(self) -> str:
        """Returns a valid access token, fetching or refreshing as necessary."""
        now = datetime.utcnow()
        if (self.tenant.nomba_access_token_enc and
            self.tenant.nomba_token_expires_at and
            self.tenant.nomba_token_expires_at > now + timedelta(minutes=5)):
            return decrypt_val(self.tenant.nomba_access_token_enc)

        if self.tenant.nomba_refresh_token_enc:
            try:
                logger.info(f"Refreshing token for tenant {self.tenant.id}")
                return await self._refresh_token()
            except Exception as e:
                logger.warning(f"Failed to refresh token for tenant {self.tenant.id}: {e}")

        logger.info(f"Issuing new token for tenant {self.tenant.id}")
        return await self._issue_token()

    async def _issue_token(self) -> str:
        client_id = decrypt_val(self.tenant.nomba_client_id_enc)
        client_secret = decrypt_val(self.tenant.nomba_client_secret_enc)

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._auth_url,
                # Auth always uses the parent account ID
                headers={"accountId": self.account_id},
                json={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret
                }
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "00":
                raise NombaAPIError(data.get("code"), data.get("description"))

            return self._save_token_data(data["data"])

    async def _refresh_token(self) -> str:
        refresh_token = decrypt_val(self.tenant.nomba_refresh_token_enc)
        access_token = decrypt_val(self.tenant.nomba_access_token_enc) if self.tenant.nomba_access_token_enc else ""

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                self._refresh_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "accountId": self.account_id
                },
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token
                }
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "00":
                raise NombaAPIError(data.get("code"), data.get("description"))

            return self._save_token_data(data["data"])

    def _save_token_data(self, token_data: dict) -> str:
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_at = parser.parse(token_data["expiresAt"]).replace(tzinfo=None)

        self.tenant.nomba_access_token_enc = encrypt_val(access_token)
        self.tenant.nomba_refresh_token_enc = encrypt_val(refresh_token)
        self.tenant.nomba_token_expires_at = expires_at

        self.session.add(self.tenant)
        self.session.commit()
        return access_token

    async def _request(self, method: str, path: str, json_data: dict = None, headers: dict = None) -> dict:
        token = await self.get_valid_token()
        req_headers = {
            "Authorization": f"Bearer {token}",
            "accountId": self.account_id,
            "Content-Type": "application/json"
        }
        # Scope requests to the sub-account when one is configured
        if self.sub_account_id:
            req_headers["subAccountId"] = self.sub_account_id
        if headers:
            req_headers.update(headers)

        url = f"{self.tenant.nomba_base_url}{path}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            if method.upper() == "GET":
                response = await client.get(url, headers=req_headers, params=json_data)
            elif method.upper() == "POST":
                response = await client.post(url, headers=req_headers, json=json_data)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=req_headers, json=json_data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            data = response.json()
            if data.get("code") not in ("00", "200"):
                raise NombaAPIError(data.get("code", "UNKNOWN"), data.get("description", str(data)))
                
            # Safely catch Verve OTP challenges ONLY on the tokenized-card endpoint
            if path == "/v1/checkout/tokenized-card-payment" and data.get("status") is False:
                err_msg = data.get("data", {}).get("message") or data.get("description") or "Operation failed"
                raise NombaAPIError("OTP_CHALLENGE_OR_FAILED", err_msg)
                
            return data.get("data", data)

    # --- RAIL 1 & INITIAL CHECKOUT ---

    async def create_checkout_order(self, order_reference: str, amount_kobo: int, customer_email: str, customer_id: str, callback_url: str, tokenize_card: bool = False) -> dict:
        """Returns checkoutLink and orderReference"""
        amount_naira_str = f"{amount_kobo / 100:.2f}"
        payload = {
            "order": {
                "orderReference": order_reference,
                "amount": amount_naira_str,
                "currency": "NGN",
                "customerEmail": customer_email,
                "customerId": customer_id,
                "callbackUrl": callback_url
            },
            "tokenizeCard": tokenize_card
        }
        return await self._request("POST", "/v1/checkout/order", json_data=payload)

    async def charge_tokenized_card(self, token_key: str, order_reference: str, amount_kobo: int, customer_email: str, customer_id: str, callback_url: str) -> dict:
        amount_naira_str = f"{amount_kobo / 100:.2f}"
        payload = {
            "order": {
                "orderReference": order_reference,
                "customerId": customer_id,
                "customerEmail": customer_email,
                "amount": amount_naira_str,
                "currency": "NGN",
                "callbackUrl": callback_url
            },
            "tokenKey": token_key
        }
        return await self._request("POST", "/v1/checkout/tokenized-card-payment", json_data=payload)

    # --- RAIL 2: VIRTUAL ACCOUNT ---

    async def create_virtual_account(self, account_ref: str, account_name: str) -> dict:
        # Hackathon requirement: VAs must be created under the sub-account.
        # The 2-VA sandbox limit is lifted on the production endpoint — configure
        # the tenant with production credentials and env="production" to use this.
        if not self.sub_account_id:
            raise ValueError("sub_account_id is required to create a Virtual Account")
        payload = {
            "accountName": account_name,
            "accountRef": account_ref
        }
        return await self._request("POST", f"/v1/accounts/virtual/{self.sub_account_id}", json_data=payload)

    # --- RAIL 3: DIRECT DEBIT ---

    async def create_mandate(self, customer_account_number: str, bank_code: str, customer_name: str, customer_phone: str, customer_email: str, merchant_reference: str) -> dict:
        # Nomba direct debit requires a 3-5 digit CBN bank code, not the 6-digit NIP code.
        # If the caller passed a NIP code, strip leading zeros to get the CBN form.
        cbn_code = bank_code.lstrip("0") if len(bank_code) > 5 else bank_code

        payload = {
            "customerAccountNumber": customer_account_number,
            "bankCode": cbn_code,
            "subscriberCode": self.sub_account_id,
            "customerName": customer_name,
            "customerAddress": "Nigeria",
            "customerAccountName": customer_name,
            "frequency": "VARIABLE",
            "narration": "Subscription mandate",
            "customerPhoneNumber": customer_phone,
            "merchantReference": merchant_reference,
            "startDate": (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "endDate": (datetime.utcnow() + timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M"),
            "customerEmail": customer_email,
            "startImmediately": True
        }
        return await self._request("POST", "/v1/direct-debits", json_data=payload)

    async def check_mandate_status(self, mandate_id: str) -> dict:
        return await self._request("GET", "/v1/direct-debits/status", json_data={"mandateId": mandate_id})

    async def debit_mandate(self, mandate_id: str, amount_kobo: int) -> dict:
        amount_naira_str = f"{amount_kobo / 100:.2f}"
        payload = {
            "mandateId": mandate_id,
            "amount": amount_naira_str
        }
        return await self._request("POST", "/v1/direct-debits/debit-mandate", json_data=payload)

    # --- BALANCE & TRANSACTIONS ---

    async def get_balance(self) -> dict:
        """Fetch the current balance for the sub-account (or parent account if no sub-account)."""
        if self.sub_account_id:
            return await self._request("GET", f"/v1/accounts/{self.sub_account_id}/balance")
        return await self._request("GET", f"/v1/accounts/{self.account_id}/balance")

    async def get_transactions(self, limit: int = 20, page: int = 1) -> dict:
        """Fetch transaction history for the sub-account."""
        account_id = self.sub_account_id or self.account_id
        return await self._request(
            "GET",
            f"/v1/transactions/accounts/{account_id}",
            json_data={"limit": limit, "page": page}
        )

    # --- TRANSFERS / PAYOUTS ---

    async def list_banks(self) -> list:
        """Returns the list of supported Nigerian banks with name and code."""
        data = await self._request("GET", "/v1/transfers/banks")
        # Nomba returns either a list directly or {banks: [...]}
        if isinstance(data, list):
            return data
        return data.get("banks", data.get("results", []))

    async def lookup_bank_account(self, account_number: str, bank_code: str) -> dict:
        """Resolve bank account number to account name (name enquiry)."""
        cbn_code = bank_code.lstrip("0") if len(bank_code) > 5 else bank_code
        return await self._request(
            "POST",
            "/v1/transfers/bank/lookup",
            json_data={"accountNumber": account_number, "bankCode": cbn_code}
        )

    async def payout_to_bank(self, amount_kobo: int, account_number: str, bank_code: str, account_name: str, narration: str = "Payout") -> dict:
        """Transfer funds from the sub-account to an external bank account."""
        if not self.sub_account_id:
            raise ValueError("sub_account_id is required for payouts")
        amount_naira_str = f"{amount_kobo / 100:.2f}"
        payload = {
            "amount": amount_naira_str,
            "accountNumber": account_number,
            "bankCode": bank_code,
            "accountName": account_name,
            "narration": narration,
            "currency": "NGN",
            "merchantTxRef": str(uuid.uuid4())
        }
        return await self._request("POST", f"/v2/transfers/bank/{self.sub_account_id}", json_data=payload)

    # --- RECONCILIATION ---

    async def fetch_transaction_status(self, order_reference: str) -> dict:
        """Fetches the real status of a transaction to handle missing webhooks."""
        # Both sandbox and production use /v1/checkout/transaction
        return await self._request("GET", "/v1/checkout/transaction", json_data={"idType": "orderReference", "id": order_reference})
