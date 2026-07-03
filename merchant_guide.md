# NombaRecur Merchant Guide

Welcome to the NombaRecur Merchant Dashboard! This dashboard allows you to manage subscriptions, plans, and customers seamlessly, abstracting away the complex Nomba API flows.

## 1. Setting up API Keys

To get started, you need your Nomba Sandbox credentials. 

**IMPORTANT NOTE FOR THE HACKATHON:** 
For the Nomba Hackathon, all teams are assigned a *sub-account* under a shared "mothership" parent account. 
- You MUST click "Setup API Keys" in the dashboard.
- **Nomba Account ID:** Enter your **Sub-Account ID** (the one emailed to you by Nomba, usually starting with `f666ef9b` or `760f...`). Do not enter the mothership ID. The backend will automatically handle passing the parent ID in headers and scoping endpoints to your sub-account!
- **Nomba Client ID:** Enter your TEST Client ID from the email.
- **Nomba Client Secret:** Enter your TEST Private Key from the email.

Once configured, the system will obtain an access token and store your NombaRecur API Key in your browser.

## 2. Testing Multiple Sub-Accounts
If you are building a multi-tenant SaaS application on top of NombaRecur, you might want to test creating multiple tenants. Since you only received one sub-account from Nomba:
1. Open a new incognito window (or clear your localStorage).
2. Create a *new* Tenant in the setup modal.
3. Input the *same* Nomba Sandbox credentials.
4. The system will issue you a completely new NombaRecur API Key. 

From the perspective of NombaRecur, you now have two completely isolated tenants, even though under the hood they both map to your single Nomba sub-account!

## 3. Creating Plans and Customers
Use the "Plans" tab to create your subscription tiers (e.g. N10,000 / month).
Use the "Customers" tab to register subscribers. You can import customers in bulk using a CSV file (must have `email` and `external_id` columns).

## 4. Checkout Simulation
Use the **Checkout Simulator** to test your integration. 
- Select a Customer and a Plan.
- Click "Generate Checkout Link".
- You will be redirected to Nomba's hosted sandbox checkout.
- **Use OTP `9999`** to simulate a successful payment.

Once the payment succeeds, Nomba sends a webhook to your server. NombaRecur will automatically tokenize the customer's card and set up the recurring billing engine. You will see the event appear in the "Immutable Log" on the Dashboard!
