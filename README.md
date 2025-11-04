(We will upload your logo to GitHub and add the link here later)

VeriCycle: Verified Value.

VeriCycle is a web application built for the Hedera Hello Future: Ascension Hackathon 2025 (Sustainability Track). It is a platform designed to upgrade the informal recycling economy in Johannesburg by replacing a high-risk, untrustworthy cash-based system with a secure, transparent, and verifiable rewards ledger built on Hedera.

This project was built by Nomathemba Ncube.

🎯 The Problem

In Johannesburg, a vital community of informal waste collectors is the backbone of the city's recycling efforts. This economy currently runs on physical cash, which creates three critical problems:

Safety: Collectors carrying a day's worth of cash are vulnerable to theft and assault.

Trust: Disputes over weight and payment are common. Collectors have no way to prove a transaction occurred or that they were paid fairly.

Opportunity: Cash transactions are invisible. Collectors have no digital footprint, making it impossible to build a financial history, get a loan, or achieve financial inclusion.

💡 The Solution: "Proof-of-Recycling"

VeriCycle solves this by introducing a "Proof-of-Recycling" protocol, which creates a verifiable bridge between a physical action (dropping off recyclables) and a secure, on-chain event.

How it works:

The Collector: Arrives at a buy-back center and generates a unique QR code from their simple web app. This QR code contains their Hedera Account ID.

The Center: Scans the collector's QR code, weighs their materials, and enters the amount (e.g., "1.5 kg").

The Magic: When the center clicks "Confirm," two things happen instantly on the Hedera test network:

HTS: The collector is paid their reward in EcoCoin (our custom HTS token) directly to their wallet.

HCS: A permanent, auditable record of the transaction (including collector, center, weight, and material) is logged to the Hedera Consensus Service.

This creates a system of verified value, giving collectors safety and a financial identity, while giving centers a secure, efficient, and cashless way to manage their operations.

💻 Technology Stack

Front-End: Deployed on Vercel (HTML, CSS, JavaScript)

Back-End: Python API built with Flask, deployed on Render

Blockchain: Hedera Network

Hedera Token Service (HTS): To create and distribute our EcoCoin reward token.

Hedera Consensus Service (HCS): To log every verified transaction as an immutable, transparent record.

Languages & Tools: Python, JavaScript (Node.js), Git

🚀 How to Run This Project Locally

To run this project, you will need Python 3.10+ and Node.js v18+.

Clone the repository:

git clone [https://github.com/commit-to-Noma/VeriCycle.git](https://github.com/commit-to-Noma/VeriCycle.git)
cd VeriCycle


Set up the Python environment:

python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt


Set up the JavaScript environment:

npm install


Create your .env file:

Create a .env file in the root directory.

Add your OPERATOR_ID and OPERATOR_KEY from the Hedera portal.

Run the Flask application:

python app.py


Open your browser and go to http://127.0.0.1:5000.

(Note: The Hedera scripts for token creation, etc., are run manually from the terminal and are not yet fully integrated with the Flask app in this MVP.)