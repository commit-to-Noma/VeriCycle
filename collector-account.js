/*
 - Purpose: Create a new Hedera account for a test collector.
 - Usage: run this script in an environment with `OPERATOR_ID` and `OPERATOR_KEY`.
 - Output: prints the new account ID and private key (DER) for storing.
*/

import "dotenv/config";
import { Client, PrivateKey, AccountCreateTransaction, Hbar } from "@hashgraph/sdk";

// Load operator credentials from environment and validate them
async function main() {
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;
  if (!operatorId || !operatorKey) throw new Error("OPERATOR_ID and OPERATOR_KEY must be set in .env");

  // Initialize Hedera client with operator
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Connecting to Hedera and creating a new collector account...");

  // Generate a new key pair for the collector account
  const newAccountPrivateKey = PrivateKey.generateECDSA();
  const newAccountPublicKey = newAccountPrivateKey.publicKey;

  // Build and submit the account-create transaction with a small initial balance
  const transaction = new AccountCreateTransaction().setKey(newAccountPublicKey).setInitialBalance(new Hbar(1));
  const txResponse = await transaction.execute(client);
  const receipt = await txResponse.getReceipt(client);
  const newAccountId = receipt.accountId;

  console.log("-----------------------------------");
  console.log("✅ New Collector Account Created!");
  console.log(`New Account ID: ${newAccountId.toString()}`);
  // Output key in structured format (not labeled) for Flask to parse
  console.log(`ACCOUNT_KEY=${newAccountPrivateKey.toStringDer()}`);
  console.log("-----------------------------------");

  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});