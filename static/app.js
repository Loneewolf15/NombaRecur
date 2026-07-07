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
let banks = [];
let txPage = 1;
let payoutHistory = [];

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
    // Auto-start tour for first-time visitors (deferred so the DOM is ready)
    setTimeout(() => startTour(), 400);
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

// Mobile Sidebar Toggle
document.getElementById("menuBtn")?.addEventListener("click", () => {
    document.getElementById("sidebar").classList.add("open");
    document.getElementById("sidebarOverlay").classList.add("open");
});
document.getElementById("sidebarOverlay")?.addEventListener("click", () => {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebarOverlay").classList.remove("open");
});

navLinks.forEach(link => {
    link.addEventListener("click", (e) => {
        e.preventDefault();
        navLinks.forEach(l => l.classList.remove("active"));
        link.classList.add("active");

        const viewId = link.getAttribute("data-view");
        pageTitle.innerText = link.innerText;

        // Auto-close mobile sidebar
        document.getElementById("sidebar").classList.remove("open");
        document.getElementById("sidebarOverlay").classList.remove("open");

        views.forEach(v => v.classList.remove("active"));
        document.getElementById(`view-${viewId}`).classList.add("active");
        
        // Close sidebar on mobile after clicking a link
        if (window.innerWidth <= 768) {
            document.getElementById("sidebar").classList.remove("open");
            document.getElementById("sidebarOverlay").classList.remove("open");
        }
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

        // Live account balance
        try {
            const balRes = await fetch(`${API_BASE}/v1/dashboard/balance`, {
                headers: { "X-API-Key": apiKey }
            });
            if (balRes.ok) {
                const balData = await balRes.json();
                const bal = balData.balance;
                if (bal) {
                    // Nomba may return availableBalance or balance (various field names)
                    const amount = bal.availableBalance ?? bal.balance ?? bal.ledgerBalance ?? bal.amount ?? null;
                    const el = document.getElementById("accountBalance");
                    if (el) el.textContent = amount != null ? `₦${Number(amount).toLocaleString('en-US', {minimumFractionDigits: 2})}` : "—";
                }
            }
        } catch (_) {}
    } catch (err) {
        console.error("Failed to load dashboard stats", err);
    }

    // Load bank list for dropdowns (fire-and-forget)
    if (banks.length === 0) loadBanks();
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
            hideLoading();
            let data = {};
            try { data = await res.json(); } catch (_) {}
            if (res.ok) {
                showMessage("Billing Triggered", `Processed ${data.subscriptions_processed ?? 0} due subscription(s).`);
                loadData();
            } else {
                const detail = data.detail || `HTTP ${res.status}`;
                showMessage("Error", `Billing failed: ${detail}`, true);
            }
        } catch (err) {
            hideLoading();
            showMessage("Error", "Could not reach the server. Check your connection.", true);
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
    const name = document.getElementById("customerName").value.trim();
    const email = document.getElementById("customerEmail").value.trim();
    const phone = document.getElementById("customerPhone").value.trim();
    const extId = document.getElementById("customerExtId").value.trim();

    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/customers/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-API-Key": apiKey
            },
            body: JSON.stringify({ name, email, phone: phone || undefined, external_id: extId })
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

window.retryVA = async function(id) {
    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/customers/${id}/provision-va`, {
            method: "POST",
            headers: { "X-API-Key": apiKey }
        });
        const data = await res.json();
        hideLoading();
        if (data.va_account_number) {
            showMessage("Success", `Virtual Account provisioned: ${data.va_account_number}`);
        } else {
            showMessage("Requery Started", "VA provisioning is running in the background. Refresh customers in a moment.");
        }
        setTimeout(() => loadData(), 3000);
    } catch (err) {
        hideLoading();
        showMessage("Error", "VA requery failed. Please try again.", true);
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

// Enroll Direct Debit Mandate
const enrollMandateForm = document.getElementById("enrollMandateForm");
if (enrollMandateForm) {
    enrollMandateForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const customerId = document.getElementById("mandateCustomer").value;
        const accountNumber = document.getElementById("mandateAccountNumber").value.trim();
        const bankCode = document.getElementById("mandateBankCode").value.trim();
        const phone = document.getElementById("mandatePhone").value.trim();

        try {
            showLoading();
            const res = await fetch(`${API_BASE}/v1/customers/${customerId}/enroll-mandate`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
                body: JSON.stringify({ account_number: accountNumber, bank_code: bankCode, phone })
            });
            const data = await res.json();
            hideLoading();
            if (res.ok) {
                showMessage("Mandate Enrolled", `Direct debit mandate created! ID: ${data.mandate_id}`);
                enrollMandateForm.reset();
                loadData();
            } else {
                showMessage("Mandate Failed", data.detail || "Failed to enroll mandate. Ensure the account number and bank code are valid.", true);
            }
        } catch (err) {
            hideLoading();
            showMessage("Error", "Network error while enrolling mandate.", true);
        }
    });
}

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
            
            // Populate Invoice View
            const customerEl = document.getElementById("simCustomer");
            const customerText = customerEl.options[customerEl.selectedIndex].text; // e.g. "Name <email@example.com>"
            const nameMatch = customerText.match(/^(.*?) </);
            const emailMatch = customerText.match(/<(.*?)>/);
            
            document.getElementById("invCustomerName").innerText = nameMatch ? nameMatch[1] : customerText;
            document.getElementById("invCustomerEmail").innerText = emailMatch ? emailMatch[1] : "";
            
            const planEl = document.getElementById("simPlan");
            const planText = planEl.options[planEl.selectedIndex].text; // e.g. "Daily (N100)"
            const amountMatch = planText.match(/\((.*?)\)/);
            const pNameMatch = planText.match(/^(.*?) \(/);
            
            document.getElementById("invPlanName").innerText = pNameMatch ? pNameMatch[1] : planText;
            document.getElementById("invPlanAmount").innerText = amountMatch ? "₦" + amountMatch[1].replace('N','') : "₦0.00";
            document.getElementById("invDate").innerText = new Date().toLocaleDateString();
            document.getElementById("invPayBtn").href = data.checkout_link;
            
            // Check for customer VA
            const customerObj = customers.find(c => c.id === customerId);
            const vaBox = document.getElementById("invVaBox");
            if (customerObj && customerObj.va_account_number) {
                document.getElementById("invVaBank").innerText = customerObj.va_bank_name || "Nomba MFB";
                document.getElementById("invVaNumber").innerText = customerObj.va_account_number;
                vaBox.classList.remove("hidden");
            } else {
                vaBox.classList.add("hidden");
            }
            
            const qrImg = document.getElementById("checkoutQR");
            qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=${encodeURIComponent(data.checkout_link)}&format=png`;
            
            // Hide invoice template by default on new generation
            document.getElementById("invoiceTemplate").classList.add("hidden");
        } else {
            showMessage("Error", JSON.stringify(data), true);
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Failed to generate checkout", true);
    }
});

document.getElementById("viewInvoiceBtn")?.addEventListener("click", () => {
    const inv = document.getElementById("invoiceTemplate");
    if (inv.classList.contains("hidden")) {
        inv.classList.remove("hidden");
    } else {
        inv.classList.add("hidden");
    }
});

document.getElementById("sendInvoiceBtn")?.addEventListener("click", async () => {
    const btn = document.getElementById("sendInvoiceBtn");
    btn.disabled = true;
    btn.innerText = "Sending...";
    
    try {
        const payload = {
            email: document.getElementById("invCustomerEmail").innerText,
            customer_name: document.getElementById("invCustomerName").innerText,
            plan_name: document.getElementById("invPlanName").innerText,
            amount: document.getElementById("invPlanAmount").innerText,
            checkout_link: document.getElementById("invPayBtn").href
        };
        
        const vaBox = document.getElementById("invVaBox");
        if (!vaBox.classList.contains("hidden")) {
            payload.va_bank_name = document.getElementById("invVaBank").innerText;
            payload.va_account_number = document.getElementById("invVaNumber").innerText;
        }
        
        const res = await fetch(`${API_BASE}/v1/subscriptions/send-invoice`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Tenant-Id": apiKey
            },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            showMessage("Success", "Invoice emailed to customer successfully!");
        } else {
            const err = await res.json();
            showMessage("Error", err.detail || "Failed to send invoice", true);
        }
    } catch (e) {
        showMessage("Error", "Network error sending invoice", true);
    } finally {
        btn.disabled = false;
        btn.innerText = "✉️ Email Invoice";
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
    list.innerHTML = customers.map(c => {
        const vaSection = c.va_account_number
            ? `<span style="color:#60a5fa;">&#127974; VA: <strong style="letter-spacing:0.5px;">${c.va_account_number}</strong>
               <button class="btn" onclick="toggleVAQR('${c.id}','${c.va_account_number}')"
                   style="padding:2px 8px;font-size:11px;margin-left:8px;background:rgba(96,165,250,0.12);color:#60a5fa;">QR</button>
               </span>
               <div id="vaqr-${c.id}" style="display:none;margin-top:8px;">
                 <img src="https://api.qrserver.com/v1/create-qr-code/?size=120x120&data=${encodeURIComponent(c.va_account_number)}&format=png"
                      width="120" height="120" style="border-radius:6px;border:2px solid rgba(96,165,250,0.3);">
               </div>`
            : `<span style="color:#64748b; font-style:italic;">VA: Not provisioned</span>
               <button class="btn" onclick="retryVA('${c.id}')" style="padding:2px 8px;font-size:11px;margin-left:8px;background:rgba(245,158,11,0.12);color:#f59e0b;">Requery VA</button>`;
        const mandateBadge = c.mandate_id
            ? `<span style="color:#10b981;font-size:11px;margin-left:8px;">&#9679; Direct Debit enrolled</span>`
            : '';
        return `
        <div class="list-item flex-between">
            <div>
                <strong>${c.name || c.email}</strong>${c.name ? ` <span style="color:#94a3b8;font-size:12px;">&lt;${c.email}&gt;</span>` : ''}${mandateBadge}
                <div style="font-size:12px; color:#94a3b8; margin-top:4px;">Ext: ${c.external_id} · ID: ${c.id}</div>
                <div style="font-size:12px; margin-top:4px;">${vaSection}</div>
            </div>
            <button class="btn btn-danger" onclick="deleteCustomer('${c.id}')">Delete</button>
        </div>`;
    }).join("") || "<p class='text-muted'>No customers registered yet.</p>";
}

window.toggleVAQR = function(customerId, vaNumber) {
    const el = document.getElementById(`vaqr-${customerId}`);
    if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
};

function renderSubscriptions() {
    const list = document.getElementById("subscriptionsList");
    if (!list) return;
    list.innerHTML = subscriptions.map(s => {
        const plan = plans.find(p => p.id === s.plan_id) || { name: 'Unknown Plan', amount_kobo: 0 };
        const customer = customers.find(c => c.id === s.customer_id) || { email: 'Unknown' };
        const statusClass = s.status === 'active' ? 'success' : s.status === 'active_manual_only' ? 'warning' : s.status === 'canceled' ? '' : 'error';
        const cancelBtn = s.status !== 'canceled' 
            ? `<button class="btn btn-danger btn-sm" onclick="cancelSubscription('${s.id}')">Cancel</button>` 
            : '';
        const displayStatus = s.status === 'active_manual_only' ? 'Requires OTP (Verve)' : s.status;
            
        return `
        <div class="list-item flex-between">
            <div>
                <strong>${customer.email}</strong> - ${plan.name} (₦${(plan.amount_kobo / 100).toFixed(2)})
                <span class="badge ${statusClass}" style="margin-left: 8px;">${displayStatus}</span>
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
    const customerOptions = customers.map(c => `<option value="${c.id}">${c.email}</option>`).join("");
    document.getElementById("simCustomer").innerHTML = customerOptions;
    document.getElementById("simPlan").innerHTML = plans.map(p => `<option value="${p.id}">${p.name} (₦${p.amount_kobo/100})</option>`).join("");
    const mandateSel = document.getElementById("mandateCustomer");
    if (mandateSel) mandateSel.innerHTML = customerOptions;
}

// ─────────────────────────────────────────────
// Banks (for dropdowns)
// ─────────────────────────────────────────────
async function loadBanks() {
    if (!apiKey) return;
    try {
        const res = await fetch(`${API_BASE}/v1/dashboard/banks`, { headers: { "X-API-Key": apiKey } });
        if (!res.ok) return;
        const data = await res.json();
        banks = data.banks || [];
        _populateBankDropdowns();
    } catch (_) {}
}

function _populateBankDropdowns() {
    if (!banks.length) return;

    // All banks — used for payouts (transfers support MFBs)
    const allOptions = banks
        .map(b => `<option value="${b.bankName || b.name} - ${b.bankCode || b.code}"></option>`)
        .join("");

    // Commercial banks only (3-digit CBN codes) — NIBSS mandates reject MFB 6-digit NIP codes
    const commercialOptions = banks
        .filter(b => {
            const code = String(b.bankCode || b.code || "");
            return code.length >= 3 && code.length <= 5;
        })
        .map(b => `<option value="${b.bankName || b.name} - ${b.bankCode || b.code}"></option>`)
        .join("");

    const payoutDl = document.getElementById("payoutBankDatalist");
    if (payoutDl) payoutDl.innerHTML = allOptions;

    const mandateDl = document.getElementById("mandateBankDatalist");
    if (mandateDl) mandateDl.innerHTML = commercialOptions;
}

function _attachDatalistToHiddenInput(inputId, hiddenId) {
    const input = document.getElementById(inputId);
    const hidden = document.getElementById(hiddenId);
    if (!input || !hidden) return;
    input.addEventListener('input', () => {
        const val = input.value;
        const match = val.match(/ - (\d{3,})$/);
        hidden.value = match ? match[1] : "";
    });
}
_attachDatalistToHiddenInput("mandateBankInput", "mandateBankCode");
_attachDatalistToHiddenInput("payoutBankInput", "payoutBankCode");

// ─────────────────────────────────────────────
// Transaction History
// ─────────────────────────────────────────────
async function loadTransactions(page = 1) {
    if (!apiKey) return;
    txPage = page;
    document.getElementById("txPageLabel").textContent = `Page ${page}`;
    const tbody = document.getElementById("txTableBody");
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">Loading...</td></tr>`;

    try {
        const res = await fetch(`${API_BASE}/v1/dashboard/transactions?page=${page}&limit=20`, {
            headers: { "X-API-Key": apiKey }
        });
        const data = await res.json();
        const txns = data.transactions;

        // Nomba may return {results:[...]} or a list directly
        const list = Array.isArray(txns) ? txns : (txns?.results || txns?.transactions || []);

        if (!list.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No transactions found.</td></tr>`;
            return;
        }

        tbody.innerHTML = list.map(tx => {
            const amount = tx.amount ?? tx.transactionAmount ?? "—";
            const type = tx.type ?? tx.transactionType ?? tx.creditDebitIndicator ?? "—";
            const status = tx.status ?? tx.transactionStatus ?? "—";
            const desc = tx.narration ?? tx.description ?? tx.remark ?? "—";
            const ref = tx.sessionId ?? tx.reference ?? tx.transactionReference ?? tx.id ?? "—";
            const date = tx.createdAt ?? tx.transactionDate ?? tx.date ?? "";
            const typeColor = type.toString().toLowerCase().includes("credit") ? "#10b981" : "#f59e0b";
            return `<tr>
                <td style="font-size:11px;color:#94a3b8;">${ref}</td>
                <td>₦${Number(amount).toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
                <td><span style="color:${typeColor};font-size:12px;">${type}</span></td>
                <td><span class="badge ${status.toLowerCase() === 'success' || status.toLowerCase() === 'successful' ? 'success' : ''}">${status}</span></td>
                <td style="font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis;">${desc}</td>
                <td style="font-size:12px;color:#94a3b8;">${date ? new Date(date).toLocaleString() : "—"}</td>
            </tr>`;
        }).join("");
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="color:#ef4444;">Failed to load transactions.</td></tr>`;
    }
}

document.getElementById("refreshTxBtn")?.addEventListener("click", () => loadTransactions(txPage));
document.getElementById("txPrevBtn")?.addEventListener("click", () => { if (txPage > 1) loadTransactions(txPage - 1); });
document.getElementById("txNextBtn")?.addEventListener("click", () => loadTransactions(txPage + 1));

// Load transactions when the tab is clicked
document.querySelector('nav a[data-view="transactions"]')?.addEventListener("click", () => {
    loadTransactions(1);
});

// ─────────────────────────────────────────────
// Payouts
// ─────────────────────────────────────────────
document.querySelector('nav a[data-view="payouts"]')?.addEventListener("click", () => {
    if (banks.length === 0) loadBanks();
});

document.getElementById("verifyAccountBtn")?.addEventListener("click", async () => {
    const accountNumber = document.getElementById("payoutAccountNumber").value.trim();
    const bankCode = document.getElementById("payoutBankCode").value.trim();
    if (!accountNumber || !bankCode) {
        return showMessage("Missing Info", "Enter account number and select a bank first.", true);
    }
    const btn = document.getElementById("verifyAccountBtn");
    btn.textContent = "Verifying...";
    btn.disabled = true;
    try {
        const res = await fetch(`${API_BASE}/v1/dashboard/lookup-bank-account`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
            body: JSON.stringify({ account_number: accountNumber, bank_code: bankCode })
        });
        const data = await res.json();
        if (res.ok) {
            const name = data.accountName ?? data.account_name ?? data.name ?? JSON.stringify(data);
            document.getElementById("payoutAccountName").value = name;
            document.getElementById("sendPayoutBtn").disabled = false;
        } else {
            showMessage("Verification Failed", data.detail || "Could not verify account.", true);
        }
    } catch (err) {
        showMessage("Error", "Network error during verification.", true);
    } finally {
        btn.textContent = "Verify";
        btn.disabled = false;
    }
});

document.getElementById("payoutForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const amountNaira = parseFloat(document.getElementById("payoutAmount").value);
    const accountNumber = document.getElementById("payoutAccountNumber").value.trim();
    const bankCode = document.getElementById("payoutBankCode").value.trim();
    const accountName = document.getElementById("payoutAccountName").value.trim();
    const narration = document.getElementById("payoutNarration").value.trim() || "NombaRecur Payout";

    if (!accountName) {
        return showMessage("Verify First", "Please verify the account name before sending.", true);
    }

    if (!confirm(`Send ₦${amountNaira.toLocaleString()} to ${accountName} (${accountNumber})?`)) return;

    try {
        showLoading();
        const res = await fetch(`${API_BASE}/v1/dashboard/payout`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
            body: JSON.stringify({
                amount_kobo: Math.round(amountNaira * 100),
                account_number: accountNumber,
                bank_code: bankCode,
                account_name: accountName,
                narration
            })
        });
        const data = await res.json();
        hideLoading();
        if (res.ok) {
            payoutHistory.unshift({ accountName, accountNumber, amountNaira, narration, time: new Date().toLocaleString() });
            renderPayoutHistory();
            e.target.reset();
            document.getElementById("sendPayoutBtn").disabled = true;
            showMessage("Payout Sent", `₦${amountNaira.toLocaleString()} sent to ${accountName} successfully.`);
            // Refresh balance
            loadData();
        } else {
            showMessage("Payout Failed", data.detail || "Transfer failed.", true);
        }
    } catch (err) {
        hideLoading();
        showMessage("Error", "Network error during payout.", true);
    }
});

function renderPayoutHistory() {
    const el = document.getElementById("payoutHistoryList");
    if (!el) return;
    if (!payoutHistory.length) {
        el.innerHTML = `<p class="text-muted">Payouts will appear here after they are sent.</p>`;
        return;
    }
    el.innerHTML = payoutHistory.map(p => `
        <div class="list-item flex-between">
            <div>
                <strong>${p.accountName}</strong> — ${p.accountNumber}
                <div style="font-size:12px;color:#94a3b8;margin-top:2px;">${p.narration} · ${p.time}</div>
            </div>
            <span style="color:#10b981;font-weight:600;">₦${Number(p.amountNaira).toLocaleString('en-US',{minimumFractionDigits:2})}</span>
        </div>
    `).join("");
}

init();

// ─────────────────────────────────────────────
// Onboarding Tour
// ─────────────────────────────────────────────
const TOUR_DONE_KEY = 'nombaRecurTourDone';

const TOUR_STEPS = [
    {
        title: 'Welcome to NombaRecur 👋',
        body: 'This quick walkthrough gets you from zero to recurring billing in about 5 minutes. Hit Next to begin, or Skip to jump straight to the dashboard.',
        target: null,
        anchor: 'center',
    },
    {
        title: '1 — Connect your Nomba account',
        body: 'Click "Setup API Keys" to paste your Nomba sandbox credentials. This creates your tenant and generates the API key that secures every request.',
        target: '#setupBtn',
        anchor: 'below',
    },
    {
        title: '2 — Create a billing plan',
        body: 'Go to Plans and define what you charge: name, amount in ₦, and interval (monthly, weekly, or demo-speed). You can have as many plans as you need.',
        target: 'nav a[data-view="plans"]',
        anchor: 'right',
        nav: 'plans',
    },
    {
        title: '3 — Register a customer',
        body: 'Head to Customers and add a subscriber by email and an external ID from your own system. NombaRecur auto-provisions a dedicated Virtual Account (NUBAN) for each customer in the background.',
        target: 'nav a[data-view="customers"]',
        anchor: 'right',
        nav: 'customers',
    },
    {
        title: '4 — Launch the first checkout',
        body: 'Open Checkout Simulator, pick a customer and plan, then generate a Nomba-hosted checkout link. In sandbox use OTP 9999 to simulate a successful card payment — the card token is saved for future renewals.',
        target: 'nav a[data-view="simulator"]',
        anchor: 'right',
        nav: 'simulator',
    },
    {
        title: '5 — Watch it run itself',
        body: "That's it! After the first payment NombaRecur handles every renewal automatically — card token first, direct debit fallback, then a checkout dunning email. Return to the Dashboard anytime to see live revenue, billing attempts, and subscription health.",
        target: 'nav a[data-view="dashboard"]',
        anchor: 'right',
        nav: 'dashboard',
    },
];

let _tourStep = 0;
let _tourHighlightEl = null;
let _tourHighlightParent = null;

const _tourOverlay = document.getElementById('tourOverlay');
const _tourCard    = document.getElementById('tourCard');

// Start the tour (force=true bypasses the "already seen" check)
function startTour(force = false) {
    if (!force && localStorage.getItem(TOUR_DONE_KEY)) return;
    _tourStep = 0;
    _showTourStep();
}

function _showTourStep() {
    const step = TOUR_STEPS[_tourStep];
    const isFirst = _tourStep === 0;
    const isLast  = _tourStep === TOUR_STEPS.length - 1;

    // Navigate to the right view when the step asks for it
    if (step.nav) {
        const navLink = document.querySelector(`nav a[data-view="${step.nav}"]`);
        if (navLink) navLink.click();
    }

    // Remove previous highlight
    _clearTourHighlight();

    // Show overlay
    _tourOverlay.style.display = 'block';

    // Build dots
    const dots = TOUR_STEPS.map((_, i) =>
        `<div class="tour-dot ${i === _tourStep ? 'active' : ''}"></div>`
    ).join('');

    // Build card HTML
    _tourCard.innerHTML = `
        <div class="tour-badge">Step ${_tourStep + 1} of ${TOUR_STEPS.length}</div>
        <h3>${step.title}</h3>
        <p>${step.body}</p>
        <div class="tour-dots">${dots}</div>
        <div class="tour-controls">
            ${!isFirst
                ? `<button class="tour-btn prev" id="tourPrevBtn">← Prev</button>`
                : ''}
            <button class="tour-btn next" id="tourNextBtn">
                ${isLast ? '🎉 Finish' : 'Next →'}
            </button>
            <button class="tour-skip" id="tourSkipBtn">Skip tour</button>
        </div>
    `;
    _tourCard.style.display = 'block';

    // Wire buttons
    document.getElementById('tourNextBtn').addEventListener('click', () => {
        if (isLast) { _endTour(); } else { _tourStep++; _showTourStep(); }
    });
    const prevBtn = document.getElementById('tourPrevBtn');
    if (prevBtn) prevBtn.addEventListener('click', () => { _tourStep--; _showTourStep(); });
    document.getElementById('tourSkipBtn').addEventListener('click', _endTour);

    // Highlight target and position card
    if (step.target) {
        const el = document.querySelector(step.target);
        if (el) {
            _applyTourHighlight(el);
            _positionCard(el, step.anchor);
            return;
        }
    }
    _positionCardCenter();
}

function _applyTourHighlight(el) {
    _tourHighlightEl = el;
    el.classList.add('tour-highlighted');

    // Lift the sidebar above the overlay when highlighting a nav link
    const sidebar = el.closest('.sidebar');
    if (sidebar) {
        sidebar.style.position = 'relative';
        sidebar.style.zIndex   = '510';
        _tourHighlightParent   = sidebar;
    }
}

function _clearTourHighlight() {
    if (_tourHighlightEl) {
        _tourHighlightEl.classList.remove('tour-highlighted');
        _tourHighlightEl = null;
    }
    if (_tourHighlightParent) {
        _tourHighlightParent.style.position = '';
        _tourHighlightParent.style.zIndex   = '';
        _tourHighlightParent = null;
    }
}

function _positionCard(el, anchor) {
    const rect  = el.getBoundingClientRect();
    const gap   = 14;
    const cardW = 300;
    const vp    = { w: window.innerWidth, h: window.innerHeight };

    _tourCard.style.transform = '';

    if (anchor === 'right') {
        let left = rect.right + gap;
        if (left + cardW > vp.w - 12) left = rect.left - cardW - gap;
        _tourCard.style.left = `${Math.max(8, left)}px`;
        _tourCard.style.top  = `${Math.max(8, Math.min(rect.top - 10, vp.h - 300))}px`;
    } else if (anchor === 'below') {
        _tourCard.style.left = `${Math.max(8, Math.min(rect.left, vp.w - cardW - 8))}px`;
        _tourCard.style.top  = `${rect.bottom + gap}px`;
    } else {
        _positionCardCenter();
    }
}

function _positionCardCenter() {
    _tourCard.style.left      = '50%';
    _tourCard.style.top       = '50%';
    _tourCard.style.transform = 'translate(-50%, -50%)';
}

function _endTour() {
    localStorage.setItem(TOUR_DONE_KEY, '1');
    _clearTourHighlight();
    _tourOverlay.style.display = 'none';
    _tourCard.style.display    = 'none';
}

// Re-trigger button in topbar
document.getElementById('tourBtn').addEventListener('click', () => startTour(true));
