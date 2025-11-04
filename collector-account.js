// This script creates a new, empty account to act as our test collector

import "dotenv/config";
import {
  Client,
  PrivateKey,
  AccountCreateTransaction,
  Hbar,
} from "@hashgraph/sdk";

async function main() {
  // 1. LOAD YOUR OPERATOR KEYS (to pay for the transaction)
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;

  if (!operatorId || !operatorKey) {
    throw new Error(
      "Error: OPERATOR_ID and OPERATOR_KEY must be set in your .env file."
    );
  }

  // 2. SET UP YOUR HEDERA CLIENT
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Connecting to Hedera and creating a new collector account...");

  // 3. GENERATE A NEW KEY PAIR FOR THE COLLECTOR
  const newAccountPrivateKey = PrivateKey.generateECDSA();
  const newAccountPublicKey = newAccountPrivateKey.publicKey;

  // 4. CREATE THE NEW ACCOUNT
  const transaction = new AccountCreateTransaction()
    .setKey(newAccountPublicKey)
    .setInitialBalance(new Hbar(1)); // Give it 1 Hbar to cover its own transactions

  // 5. EXECUTE AND GET THE NEW ACCOUNT ID
  const txResponse = await transaction.execute(client);
  const receipt = await txResponse.getReceipt(client);
  const newAccountId = receipt.accountId;

  console.log("-----------------------------------");
  console.log("✅ New Collector Account Created!");
  console.log(`New Account ID: ${newAccountId.toString()}`);
  console.log(`New Account Private Key (DER): ${newAccountPrivateKey.toStringDer()}`);
  console.log("-----------------------------------");
  console.log("!! IMPORTANT: Copy these two values into your .env file NOW !!");

  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});