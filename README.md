<div align="center">
  <img src="https://nomba-recur.vercel.app/static/nomba_logo.png" alt="NombaRecur Logo" width="120" />
  <h1>NombaRecur</h1>
  <p><strong>A multi-rail recurring billing engine built on top of Nomba Checkout.</strong></p>
  <p><em>Final Submission for the DevCareer x Nomba Hackathon 2026</em></p>
</div>

---

## 🚀 Live Demo
**Platform URL**: [https://nomba-recur.vercel.app](https://nomba-recur.vercel.app)

---

## 💡 The Problem
In Nigeria, SaaS platforms and service providers struggle with automated recurring billing. Relying solely on card tokenization often fails due to network downtime, expired cards, or strict issuer rules (like Verve requiring per-transaction OTPs). When a card charge fails, the merchant loses revenue, and there is no reliable fallback mechanism.

## 🛠 The Solution: NombaRecur
**NombaRecur** is an abstraction layer and subscription engine that sits between developers and the Nomba API. It provides a Stripe-like Billing experience specifically optimized for the Nigerian market using Nomba's infrastructure.

### Multi-Rail Fallback System
We didn't just build a card-tokenization wrapper. NombaRecur uses a **Multi-Rail strategy**:
1. **Primary Rail (Tokenized Cards)**: Automatically charges saved Visa/Mastercard tokens via Merchant-Initiated Transactions (MIT).
2. **Secondary Rail (Virtual Accounts)**: If a card fails, or if a user holds a Verve card (which enforces per-transaction OTPs), NombaRecur seamlessly falls back to a dedicated **Nomba Virtual Account** mapped to that specific customer. The customer can do a simple bank transfer to their VA, and NombaRecur's webhook listener automatically intercepts the transfer and renews their subscription.

### Built for Developers
Instead of writing complex integration logic, developers can create a Tenant in NombaRecur and integrate with our simplified REST API. NombaRecur handles:
- Plan management
- Scheduler cron jobs (auto-renewals, retries, and dunning)
- Fallback routing
- Idempotent Webhook handling
- State reconciliation

---

## 🔍 Going Beyond the Brief: What We Discovered in Production
The prompt asked us to build something that solves a real problem and *show that it works*. To do that, **we tested NombaRecur extensively in the LIVE environment with real money**. 

In doing so, we uncovered structural differences between Nomba's Sandbox and Live environments, and adapted NombaRecur's reconciliation engine to survive them:

1. **The Verve Card OTP Challenge**: We discovered that Verve cards enforce per-transaction OTPs, making them fundamentally incompatible with silent Merchant-Initiated Transactions. When our engine detects a Verve card, it intelligently tags the subscription as `active_manual_only` and falls back to Virtual Account billing rather than blindly retrying and failing.
2. **The Live Parity Bug**: In Sandbox, querying a pending transaction via `/v1/checkout/transaction` gracefully returns a `200 OK` with `success: false`. However, we discovered that in the **Live** environment, doing the same returns a fatal `400 Bad Request`. Standard HTTP clients crash on this. **We built a custom resilient catch-block in our Scheduler** that specifically parses Nomba's `400` errors so that our background reconciliation loop never crashes, even when Nomba's live API acts unexpectedly.

*(We have documented these API findings in a separate bug report for the Nomba engineering team, demonstrating our deep dive into the platform).*

---

## 💻 Tech Stack
- **Backend Framework**: Python / FastAPI (High-performance, async architecture).
- **Database**: PostgreSQL with SQLModel (SQLAlchemy 2.0).
- **Frontend**: Vanilla JS, raw CSS (No Tailwind bloat, highly optimized glassmorphism UI).
- **Hosting / CI/CD**: Vercel (Serverless functions) and Supabase.
- **Integration**: Nomba API (Checkout, Tokenization, Virtual Accounts, Webhooks).

---

## 🚀 Key Features
* **Tenant Multi-Tenancy**: Built to support multiple businesses simultaneously.
* **Smart Scheduler**: Background worker that processes due subscriptions.
* **Webhook Engine**: Idempotent listener for `payment_success` and `virtual_account_credit` events.
* **Dashboard Analytics**: Real-time view into MRR, active subscribers, and recent billing attempts.
* **Developer API**: Fully documented endpoints for external integrations.

---

## 🚦 Local Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/Loneewolf15/NombaRecur.git
   cd NombaRecur
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up Environment Variables**
   Create a `.env` file in the root directory:
   ```env
   DATABASE_URL=postgresql://user:password@localhost:5432/nombarecur
   SECRET_KEY=your_super_secret_key
   NOMBA_WEBHOOK_SECRET=your_nomba_webhook_secret
   ```

5. **Run the Application**
   ```bash
   uvicorn app.main:app --reload
   ```

6. **Access the Application**
   - Web Portal: `http://localhost:8000/v1/portal/login`
   - API Docs: `http://localhost:8000/docs`

---
*Built with ❤️ by Divine Osarumwense Victor and the NombaRecur Team for the DevCareer x Nomba Hackathon 2026.*
