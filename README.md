# VeriCycle - Verified Value ♻️

**Hedera Hello Future: Ascension Hackathon 2025 (Sustainability Track)**

VeriCycle is a Web3 financial infrastructure designed to gamify and incentivize recycling at a global scale. We replace high-risk cash payments with **EcoCoin** which is a secure, verifiable reward token built on the Hedera network.

While our pilot focuses on South Africa's informal sector, our technology is a **Universal Recycling Protocol** designed to streamline waste management for every city on earth.

**Built by:** Nomathemba Ncube (The One Who Man Team)

---

## 🎯 The Problem: A Broken Incentive Model
Recycling is currently a "burden" for citizens and a "logistics nightmare" for cities.
1.  **The Informal Sector (The Job):** 90,000+ waste pickers in SA are unbanked and face theft risks daily because they are paid in physical cash.
2.  **The Household (The Habit):** Regular citizens have no incentive to recycle other than "feeling good."
3.  **The City (The Cost):** Municipalities spend millions on fuel collecting unsegregated waste, while streets remain dirty.

## 💡 The Solution: Proof-of-Recycling
VeriCycle solves this by turning recycling into a **verifiable financial asset**.
-   **For the Worker:** A digital wallet that builds a "Proof of Income" credit score.
-   **For the Household:** A gamified reward system (EcoCoin) that pays you to keep your city clean.
-   **For the City:** Real-time data on waste diversion to optimize logistics.

---

## 🧪 How to Test (The Demo Flow)

To experience the full "Center-to-Collector" verification loop without session conflicts, please follow this **Dual-Persona** guide.

### 🟢 Step 1: Setup (The Two Personas)
Because browsers share cookies, you must use **two different window types** to simulate two different users at once.

1.  **Tab 1 (Normal Window) → The Collector**
    * **Log In:** `demo@vericycle.com`
    * **Password:** `H3dera!2025`
    * *You will see the Collector Dashboard with an initial balance of 1175 ECO.*

2.  **Tab 2 (Incognito/Private Window) → The Recycling Center**
    * **Log In:** `mpact@vericycle.com`
    * **Password:** `Centerh3dera!`
    * *You will see the Center Dashboard.*

---

### 🔵 Step 2: The Main Flow (Verify & Earn)

1.  **In Tab 2 (Center):**
    * Click the green **"Scan Collector QR Code"** button.
    * Select **"Aluminum Cans"** and enter a weight (e.g., `10`).
    * Click **"Verify & Pay"**.
    * *Result:* You will see a green "Verification Successful!" banner, and the transaction will appear in the "Today" list.

2.  **Switch to Tab 1 (Collector):**
    * **Magic Moment:** The balance should update automatically (via Broadcast Channel).
    * *Backup:* If your browser blocks cross-window signals, simply click the **"Refresh Balance"** button at the bottom.
    * *Result:* Confetti fires, balance increases, and the new transaction appears at the top of "Recent Activity."

3.  **Cash Out (Collector):**
    * Click the green **"Wallet & Exchange"** button.
    * **Step 1:** Click **"Swap Now"** to convert ECO to HBAR (Simulated DEX).
    * **Step 2:** Click **"Withdraw to Bank"** to cash out to ZAR.
    * *Result:* You are redirected to the Dashboard, and a red "Withdrawal" entry appears in your history.

---

### 🔎 Step 3: Other Features to Explore

While logged in as the **Collector (`demo@vericycle.com`)**, check out these features:

* **📄 Proof of Income Report:** Click **"Download PDF"** on the dashboard to see the generated financial statement based on your HCS history.
* **🚚 Smart Logistics:** Click **"Request a Pickup"**. This mockup auto-detects your neighborhood (Sandton) and offers a "High-Activity Discount."
* **🌍 Live Platform Stats:** Go to the **Home** page to see the "Platform Growth" chart and "Live Activity" feed visualizing network performance.
* **🔐 Self-Custody Wallet:** Go to **Profile** to see your real Hedera Account ID and Private Key, proving you own your data.

## 💼 Business Model (Feasibility)
VeriCycle is not a charity; it is a high-volume infrastructure play. We monetize the **data** and **efficiency**, not the user.

### 1. Municipal Data Services (B2G)
* **The Value:** Waste pickers save SA municipalities ~R750 million annually in landfill airspace.
* **Our Revenue:** We charge the city a **Data Fee of R0.10 per kg** verified.
* **The Scale:** At 100 tonnes/day, this generates **~R10,000/day** in revenue while saving the city 10x that amount.

### 2. EPR Compliance Credits (B2B)
* **The Value:** Brands (e.g., Coca-Cola) are legally required to prove they recycle.
* **Our Revenue:** We sell **"Verified Plastic Credits"** at **R500 per tonne** based on our immutable Hedera logs.

### 3. Financial Lead Generation (B2B)
* **The Value:** Banks spend huge amounts to acquire new customers.
* **Our Revenue:** We charge banks a **R50 Referral Fee** for every "Proof of Income" report that successfully opens a new bank account.
* **The Scale:** With 90,000 unbanked collectors, this is a **R4.5 Million** untapped market opportunity.

---

## 🌍 Global Vision & Impact
We are launching in **South Africa** to solve a critical humanitarian crisis (safety for waste pickers), but the model scales globally:

1.  **The Professional Recycler:** Gets safety, dignity, and banking access.
2.  **The Eco-Conscious Citizen:** Gets rewarded for habits they already have.
3.  **The New Adopter:** Is incentivized to start recycling for the first time to earn "Beer Money" or discounts.

**Network Impact (Success Metrics):**
* **User Volume:** Potential to onboard **90,000+ new users** in SA alone.
* **Transaction Velocity:** Recycling happens daily. 90,000 users × 5 drops/day = **450,000 daily transactions** on Hedera HCS.

---

## 💻 Technology Stack
-   **Blockchain:** Hedera (HTS for Tokens, HCS for Immutable Logs, Account Service for Wallets).
-   **Backend:** Python (Flask), SQLAlchemy.
-   **Frontend:** HTML5, CSS3, JavaScript (Chart.js).
-   **Deployment:** Render.

---

## 🔗 Links
-   **Live Demo:** https://vericycle.onrender.com
-   **Pitch Deck:** https://github.com/commit-to-Noma/VeriCycle/blob/main/Vericycle%20Pitch%20Deck.pdf
-   **Video Demo:** https://youtu.be/Tj-i2-C7dGQ
