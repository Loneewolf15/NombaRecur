const API_BASE = ""; // relative since it's served from same host
let apiKey = localStorage.getItem("nombaRecurApiKey");
let tenantEnv = localStorage.getItem("nombaRecurEnv") || "sandbox";

// VA retry state
let _vaRetryCustomerId = null;
let _vaRetryCustomerName = null;

// Elements
const setupModal = document.getElementById("setupModal");
const setupBtn = document.getElementById("setupBtn");
const setupForm = document.getElementById("setupForm");
const tenantStatus = document.getElementById("tenantStatus");
const navLinks = document.querySelectorAll("nav a");
const views = document.querySelectorAll(".view");
const pageTitle = document.getElementById("pageTitle");

const messageModal = document.getElementById("messageModal");
const messageModalTitle = document.getElementById("messageModalTitle");
const messageModalText = document.getElementById("messageModalText");
const messageModalBtn = document.getElementById("messageModalBtn");
const loadingOverlay = document.getElementById("loadingOverlay");

// State
let plans = [];
let customers = [];
let subscriptions = [];
let revenueChartInstance = null;
let railChartInstance = null;

// Init
function init() {
    if (apiKey) {
        setupModal.classList.remove("active");
        const envLabel = tenantEnv === "production" ? "Production" : "Sandbox";
        tenantStatus.innerHTML = `<span class="status-indicator green"></span> Configured (${envLabel})`;
        loadData();
    } else {
        setupModal.classList.add("active");
    }
}

// UI Helpers
function showMessage(title, text, isError = false) {
    messageModalTitle.innerText = title;
    messageModalText.innerText = text;
    messageModalTitle.style.color = isError ? "#ef4444" : "var(--text-main)";
    messageModal.classList.add("active");
}

function showLoading() {
    loadingOverlay.classList.add("active");
}

function hideLoading() {
    loadingOverlay.classList.remove("active");
}

messageModalBtn.addEventListener("click", () => {
    messageModal.classList.remove("active");
});

// VA retry modal
const vaRetryModal = document.getElementById("vaRetryModal");
document.getElementById("vaRetryDismissBtn").addEventListener("click", () => {
    vaRetryModal.classList.remove("active");
});
document.getElementById("vaRetryBtn").addEventListener("click", async () => {
    if (!_vaRetryCustomerId) return;
    document.getElementById("vaRetryBtn").textContent = "Retrying...";
    document.getElementById("vaRetryBtn").disabled = true;
    try {
        const res = await fetch(`${API_BASE}/v1/customers/${_vaRetryCustomerId}/provision-va`, {
            method: "POST",
            headers: { "X-API-Key": apiKey }
        });
        const data = await res.json();
        vaRetryModal.classList.remove("active");
        if (data.va_account_number) {
            showMessage("VA Ready", `Virtual Account provisioned: ${data.va_account_number}`);
        } else {
            showMessage("Retry Started", "VA provisioning is running in the background. Refresh customers in a moment.");
        }
        // Refresh customer list to show updated VA number
        setTimeout(() => loadData(), 3000);
    } catch (err) {
        showMessage("Error", "VA retry failed. Please try again.", true);
    } finally {
        document.getElementById("vaRetryBtn").textContent = "Retry VA Creation";
        document.getElementById("vaRetryBtn").disabled = false;
    }
});

function showVARetryModal(customerId, customerName) {
    _vaRetryCustomerId = customerId;
    _vaRetryCustomerName = customerName;
    document.getElementById("vaRetryText").textContent =
        `Customer "${customerName}" was created successfully, but their dedicated Virtual Account (NUBAN) could not be provisioned automatically. This may be due to a Nomba API issue. Click retry to try again.`;
    vaRetryModal.classList.add("active");
}

async function pollForVA(customerId, customerName, attemptsLeft = 3) {
    if (attemptsLeft <= 0) {
        showVARetryModal(customerId, customerName);
        return;
    }
    await new Promise(r => setTimeout(r, 3000));
    try {
        const res = await fetch(`${API_BASE}/v1/customers/${customerId}`, {
            headers: { "X-API-Key": apiKey }
        });
        if (res.ok) {
            const customer = await res.json();
            if (customer.va_account_number) {
                // VA ready — refresh the list silently
                loadData();
                return;
            }
        }
    } catch (_) {}
    pollForVA(customerId, customerName, attemptsLeft - 1);
}

// Navigation
navLinks.forEach(link => {
    link.addEventListener("click", (e) => {
        e.preventDefault();
        navLinks.forEach(l => l.classList.remove("active"));
        link.classList.add("active");

        const viewId = link.getAttribute("data-view");
        pageTitle.innerText = link.innerText;

        views.forEach(v => v.classList.remove("active"));
        document.getElementById(`view-${viewId}`).classList.add("active");
    });
});

setupBtn.addEventListener("click", () => setupModal.classList.add("active"));
document.getElementById("closeModalBtn").addEventListener("click", () => setupModal.classList.remove("active"));

// Setup Tenant
setupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const env = document.getElementById("nombaEnv").value;
    const subAccountId = document.getElementById("nombaSubAccountId").value.trim();
    const payload = {
        name: "Demo SaaS",
        email: "demo@example.com",
        nomba_account_id: document.getElementById("nombaAccountId").value.trim(),
        nomba_sub_account_id: subAccountId || undefined,
        nomba_client_id: document.getElementById("nombaClientId").value.trim(),
        nomba_client_secret: document.getElementById("nombaClientSecret").value,
        webhook_url: document.getElementById("webhookUrl").value,
        env
    };

    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/tenants/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        hideLoading();

        if (data.api_key) {
            apiKey = data.api_key;
            tenantEnv = data.env || env;
            localStorage.setItem("nombaRecurApiKey", apiKey);
            localStorage.setItem("nombaRecurEnv", tenantEnv);
            setupModal.classList.remove("active");
            init();
            showMessage("Success", `Tenant configured on ${tenantEnv === "production" ? "Production" : "Sandbox"}! API Key saved.`);
        } else {
            console.error("Setup error:", data);
            showMessage("Error", "Something went wrong. Check logs.", true);
        }
    } catch (err) {
        hideLoading();
        console.error(err);
        showMessage("Error", "Request failed. Is the server running?", true);
    }
});

// Load Data — fetch fresh from API instead of localStorage
async function loadData() {
    if (!apiKey) return;

    // Fetch plans, customers, and subscriptions from the API
    try {
        const [plansRes, customersRes, subsRes] = await Promise.all([
            fetch(`${API_BASE}/v1/plans/`, { headers: { "X-API-Key": apiKey } }),
            fetch(`${API_BASE}/v1/customers/`, { headers: { "X-API-Key": apiKey } }),
            fetch(`${API_BASE}/v1/subscriptions/`, { headers: { "X-API-Key": apiKey } })
        ]);
        if (plansRes.ok) plans = await plansRes.json();
        if (customersRes.ok) customers = await customersRes.json();
        if (subsRes.ok) subscriptions = await subsRes.json();
    } catch (err) {
        console.error("Failed to load plans/customers/subs", err);
    }

    renderPlans();
    renderCustomers();
    renderSubscriptions();
    updateSimDropdowns();

    // Load dashboard stats
    try {
        const res = await fetch(`${API_BASE}/v1/dashboard/`, {
            headers: { "X-API-Key": apiKey }
        });
        if (res.ok) {
            const stats = await res.json();
            document.getElementById("activeSubsCount").textContent = stats.active_subscriptions;
            document.getElementById("totalRevenue").textContent = `₦${stats.total_revenue_ngn.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
            document.getElementById("pendingRenewals").textContent = stats.pending_renewals;

            const tableBody = document.querySelector("#view-dashboard table tbody");
            tableBody.innerHTML = "";
            if (stats.recent_attempts && stats.recent_attempts.length > 0) {
                renderAttemptsTable(tableBody, stats.recent_attempts);
            } else {
                tableBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">No billing attempts yet.</td></tr>`;
            }
        }
        
        // Fetch and render analytics
        const analyticsRes = await fetch(`${API_BASE}/v1/dashboard/analytics`, {
            headers: { "X-API-Key": apiKey }
        });
        if (analyticsRes.ok) {
            const analytics = await analyticsRes.json();
            renderCharts(analytics);
        }
    } catch (err) {
        console.error("Failed to load dashboard stats", err);
    }
}

function renderCharts(data) {
    // Revenue Line Chart
    const revCtx = document.getElementById('revenueChart').getContext('2d');
    if (revenueChartInstance) revenueChartInstance.destroy();
    revenueChartInstance = new Chart(revCtx, {
        type: 'line',
        data: {
            labels: data.revenue_trend.labels,
            datasets: [{
                label: 'Revenue (₦)',
                data: data.revenue_trend.data,
                borderColor: '#7c3aed',
                tension: 0.3,
                fill: true,
                backgroundColor: 'rgba(124, 58, 237, 0.1)'
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });

    // Rail Pie Chart
    const railCtx = document.getElementById('railChart').getContext('2d');
    if (railChartInstance) railChartInstance.destroy();
    railChartInstance = new Chart(railCtx, {
        type: 'doughnut',
        data: {
            labels: ['Card (Initial)', 'Card (Recurring)', 'Direct Debit', 'Virtual Account'],
            datasets: [{
                data: [
                    data.rail_breakdown.card_initial,
                    data.rail_breakdown.card_recurring,
                    data.rail_breakdown.direct_debit,
                    data.rail_breakdown.virtual_account
                ],
                backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6']
            }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
    });
}

function renderAttemptsTable(tableBody, attempts) {
    tableBody.innerHTML = "";
    attempts.forEach(attempt => {
        const tr = document.createElement("tr");
        const statusClass = attempt.status === 'success' ? 'success' : attempt.status === 'pending' ? '' : 'error';
        tr.innerHTML = `
            <td>${attempt.merchant_tx_ref}</td>
            <td>₦${(attempt.amount_kobo / 100).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
            <td><span class="badge" style="background:var(--bg-lighter)">${attempt.rail}</span></td>
            <td><span class="badge ${statusClass}">${attempt.status}</span></td>
            <td>${new Date(attempt.created_at).toLocaleString()}</td>
        `;
        tableBody.appendChild(tr);
    });
}

// Reconcile Pending
const reconcileBtn = document.getElementById("reconcileBtn");
if (reconcileBtn) {
    reconcileBtn.addEventListener("click", async () => {
        try {
            showLoading();
            const res = await fetch(`${API_BASE}/v1/dashboard/reconcile-pending`, {
                method: "POST",
                headers: { "X-API-Key": apiKey }
            });
            const data = await res.json();
            hideLoading();

            if (res.ok) {
                let msg = `Processed: ${data.total_processed}\nSuccess: ${data.details.success}\nFailed: ${data.details.failed}\nErrors: ${data.details.errors}`;
                showMessage("Reconciliation Complete", msg);
                loadData();
            } else {
                showMessage("Error", "Failed to run reconciliation.", true);
            }
        } catch (err) {
            hideLoading();
            showMessage("Error", "Network error while reconciling.", true);
        }
    });
}

// Trigger Billing Now
const triggerBillingBtn = document.getElementById("triggerBillingBtn");
if (triggerBillingBtn) {
    triggerBillingBtn.addEventListener("click", async () => {
        try {
            showLoading();
            const res = await fetch(`${API_BASE}/v1/dashboard/trigger-billing`, {
                method: "POST",
                headers: { "X-API-Key": apiKey }
            });
            const data = await res.json();
            hideLoading();
            if (res.ok) {
                showMessage("Billing Triggered", `Processed ${data.subscriptions_processed} due subscription(s).`);
                loadData();
            } else {
                showMessage("Error", "Failed to trigger billing.", true);
            }
        } catch (err) {
            hideLoading();
            showMessage("Error", "Network error.", true);
        }
    });
}

// HTTP QUERY Filter
const filterBtn = document.getElementById("filterBtn");
if (filterBtn) {
    filterBtn.addEventListener("click", async () => {
        const status = document.getElementById("filterStatus").value;
        const payload = { limit: 10 };
        if (status) payload.status = status;

        try {
            showLoading();
            const res = await fetch(`${API_BASE}/v1/dashboard/search`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-API-Key": apiKey
                },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            hideLoading();

            if (res.ok) {
                const tableBody = document.querySelector("#view-dashboard table tbody");
                if (data && data.length > 0) {
                    renderAttemptsTable(tableBody, data);
                } else {
                    tableBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">No matches found.</td></tr>`;
                }
            } else {
                showMessage("Error", "Failed to run filter.", true);
            }
        } catch (err) {
            hideLoading();
            showMessage("Error", "Network error while filtering.", true);
        }
    });
}

// Create Plan
document.getElementById("createPlanForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("planName").value;
    const amount = document.getElementById("planAmount").value;
    const interval = document.getElementById("planInterval").value;

    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/plans/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": apiKey
            },
            body: JSON.stringify({ name, amount_kobo: parseInt(amount) * 100, interval })
        });
        const data = await res.json();
        hideLoading();

        if (data.id) {
            plans.push(data);
            renderPlans();
            updateSimDropdowns();
            e.target.reset();
            showMessage("Success", "Plan created successfully!");
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to create plan", true);
    }
});

// Delete Plan
window.deletePlan = async function(id) {
    if (!confirm("Are you sure you want to delete this plan?")) return;
    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/plans/${id}`, {
            method: "DELETE",
            headers: { "X-API-Key": apiKey }
        });
        hideLoading();
        if (res.ok) {
            plans = plans.filter(p => p.id !== id);
            renderPlans();
            updateSimDropdowns();
            showMessage("Success", "Plan deleted successfully!");
        } else {
            showMessage("Error", "Failed to delete plan", true);
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to delete plan", true);
    }
};

// Create Customer
document.getElementById("createCustomerForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("customerEmail").value;
    const extId = document.getElementById("customerExtId").value;

    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/customers/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": apiKey
            },
            body: JSON.stringify({ email, external_id: extId })
        });
        const data = await res.json();
        hideLoading();

        if (data.id) {
            customers.push(data);
            renderCustomers();
            updateSimDropdowns();
            e.target.reset();
            if (data.va_account_number) {
                showMessage("Success", `Customer created! VA: ${data.va_account_number}`);
            } else {
                // VA is being provisioned in the background — poll for it
                showMessage("Customer Created", "Virtual Account provisioning is in progress...");
                pollForVA(data.id, data.name || data.email);
            }
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to create customer", true);
    }
});

// Delete Customer
window.deleteCustomer = async function(id) {
    if (!confirm("Are you sure you want to delete this customer?")) return;
    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/customers/${id}`, {
            method: "DELETE",
            headers: { "X-API-Key": apiKey }
        });
        hideLoading();
        if (res.ok) {
            customers = customers.filter(c => c.id !== id);
            renderCustomers();
            updateSimDropdowns();
            showMessage("Success", "Customer deleted successfully!");
        } else {
            showMessage("Error", "Failed to delete customer", true);
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to delete customer", true);
    }
};

// Import CSV
document.getElementById("importCsvBtn").addEventListener("click", async () => {
    const fileInput = document.getElementById("csvFileInput");
    if (!fileInput.files.length) {
        return showMessage("Error", "Please select a CSV file first.", true);
    }

    const file = fileInput.files[0];
    const reader = new FileReader();
    reader.onload = async (e) => {
        const text = e.target.result;
        const rows = text.split("\n").map(r => r.trim()).filter(r => r);
        if (rows.length < 2) return showMessage("Error", "CSV is empty or invalid.", true);

        const headers = rows[0].split(",").map(h => h.trim().toLowerCase());
        const emailIdx = headers.indexOf("email");
        const extIdIdx = headers.indexOf("external_id");

        if (emailIdx === -1 || extIdIdx === -1) {
            return showMessage("Error", "CSV must have 'email' and 'external_id' headers.", true);
        }

        showLoading();
        let successCount = 0;

        for (let i = 1; i < rows.length; i++) {
            const cols = rows[i].split(",").map(c => c.trim());
            if (cols.length < 2) continue;

            const email = cols[emailIdx];
            const extId = cols[extIdIdx];

            try {
                const res = await fetch(`${API_BASE}/v1/customers/`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-API-Key": apiKey
                    },
                    body: JSON.stringify({ email, external_id: extId })
                });
                const data = await res.json();
                if (data.id) {
                    customers.push(data);
                    successCount++;
                    if (!data.va_account_number) {
                        // Poll quietly — don't spam modals for bulk import
                        pollForVA(data.id, data.name || data.email, 2);
                    }
                }
            } catch (err) {
                console.error("Failed to import", email);
            }
        }

        renderCustomers();
        updateSimDropdowns();
        hideLoading();
        fileInput.value = "";

        if (successCount > 0) {
            showMessage("Success", `Imported ${successCount} customers successfully!`);
        } else {
            showMessage("Error", "Failed to import any customers.", true);
        }
    };
    reader.readAsText(file);
});

// Simulate Checkout
document.getElementById("simulateForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const customerId = document.getElementById("simCustomer").value;
    const planId = document.getElementById("simPlan").value;

    // Use tenant's configured webhook URL, fall back to current origin
    const callbackUrl = `${window.location.origin}/v1/webhooks/nomba`;

    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/subscriptions/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": apiKey
            },
            body: JSON.stringify({ customer_id: customerId, plan_id: planId, callback_url: callbackUrl })
        });
        const data = await res.json();
        hideLoading();

        if (data.checkout_link) {
            document.getElementById("checkoutResult").classList.remove("hidden");
            document.getElementById("checkoutLinkBtn").href = data.checkout_link;
        } else {
            showMessage("Error", JSON.stringify(data), true);
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to generate checkout", true);
    }
});

// Renders
function renderPlans() {
    const list = document.getElementById("plansList");
    list.innerHTML = plans.map(p => `
        <div class="list-item flex-between">
            <div>
                <strong>${p.name}</strong> - ₦${(p.amount_kobo / 100).toFixed(2)} / ${p.interval}
                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">ID: ${p.id}</div>
            </div>
            <button class="btn btn-danger" onclick="deletePlan('${p.id}')">Delete</button>
        </div>
    `).join("") || "<p class='text-muted'>No plans created yet.</p>";
}

function renderCustomers() {
    const list = document.getElementById("customersList");
    list.innerHTML = customers.map(c => `
        <div class="list-item flex-between">
            <div>
                <strong>${c.email}</strong> (Ext: ${c.external_id})
                ${c.va_account_number ? `<span style="font-size:11px; background:#1e3a5f; color:#60a5fa; padding:2px 6px; border-radius:4px; margin-left:6px;">VA: ${c.va_account_number}</span>` : ''}
                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">ID: ${c.id}</div>
            </div>
            <button class="btn btn-danger" onclick="deleteCustomer('${c.id}')">Delete</button>
        </div>
    `).join("") || "<p class='text-muted'>No customers registered yet.</p>";
}

function renderSubscriptions() {
    const list = document.getElementById("subscriptionsList");
    if (!list) return;
    list.innerHTML = subscriptions.map(s => {
        const plan = plans.find(p => p.id === s.plan_id) || { name: 'Unknown Plan', amount_kobo: 0 };
        const customer = customers.find(c => c.id === s.customer_id) || { email: 'Unknown' };
        const statusClass = s.status === 'active' ? 'success' : s.status === 'canceled' ? '' : 'error';
        const cancelBtn = s.status !== 'canceled' 
            ? `<button class="btn btn-danger" onclick="cancelSubscription('${s.id}')">Cancel</button>`
            : `<span class="text-muted">Canceled</span>`;
            
        return `
        <div class="list-item flex-between">
            <div>
                <strong>${customer.email}</strong> - ${plan.name} (₦${(plan.amount_kobo / 100).toFixed(2)})
                <span class="badge ${statusClass}" style="margin-left: 8px;">${s.status}</span>
                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Next Billing: ${new Date(s.next_billing_at).toLocaleString()}</div>
            </div>
            ${cancelBtn}
        </div>
        `;
    }).join("") || "<p class='text-muted'>No subscriptions yet.</p>";
}

window.cancelSubscription = async function(id) {
    if (!confirm("Are you sure you want to cancel this subscription? It will stop immediately.")) return;
    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/subscriptions/${id}/cancel`, {
            method: "POST",
            headers: { "X-API-Key": apiKey }
        });
        hideLoading();
        if (res.ok) {
            showMessage("Success", "Subscription canceled successfully!");
            loadData();
        } else {
            showMessage("Error", "Failed to cancel subscription", true);
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to cancel subscription", true);
    }
};

function updateSimDropdowns() {
    document.getElementById("simCustomer").innerHTML = customers.map(c => `<option value="${c.id}">${c.email}</option>`).join("");
    document.getElementById("simPlan").innerHTML = plans.map(p => `<option value="${p.id}">${p.name} (₦${p.amount_kobo/100})</option>`).join("");
}

init();
