// This script is now a tool that accepts arguments from the command line

import "dotenv/config";
import {
  Client,
  PrivateKey,
  TransferTransaction,
  AccountId,
} from "@hashgraph/sdk";

// This is the main function
async function main() {
  
  // --- THIS IS THE NEW PART ---
  // Read arguments from the command line
  // process.argv[0] is "node"
  // process.argv[1] is "4-transfer-reward.js"
  // process.argv[2] is the Collector ID (e.g., "0.0.7191569")
  // process.argv[3] is the Amount (e.g., "250")
  const collectorId = process.argv[2];
  const rewardAmount = parseInt(process.argv[3]); // Convert text "250" to number 250
  
  if (!collectorId || !rewardAmount) {
    throw new Error("Error: Missing Collector ID or Reward Amount. Usage: node 4-transfer-reward.js [COLLECTOR_ID] [AMOUNT]");
  }
  // --- END OF NEW PART ---


  // 1. LOAD YOUR KEYS AND IDs
  const operatorId = process.env.OPERATOR_ID; // This is the Treasury Account
  const operatorKey = PrivateKey.fromStringDer(process.env.OPERATOR_KEY); // Treasury's key
  const ecoCoinTokenId = process.env.ECOCOIN_TOKEN_ID;

  if (!operatorId || !operatorKey || !ecoCoinTokenId) {
    throw new Error("Error: Please check your .env file. All variables must be set.");
  }
  
  // 2. SET UP YOUR HEDERA CLIENT
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log(`Connecting to Hedera and sending ${rewardAmount} ECO to ${collectorId}...`);

  // 3. BUILD THE TRANSACTION (using our new variables)
  const transaction = await new TransferTransaction()
    .addTokenTransfer(ecoCoinTokenId, operatorId, -rewardAmount) // From Treasury
    .addTokenTransfer(ecoCoinTokenId, collectorId, rewardAmount) // To Collector
    .freezeWith(client);

  // 4. SIGN WITH THE SENDER'S KEY (The Treasury)
  const signedTx = await transaction.sign(operatorKey);

  // 5. SUBMIT & GET RECEIPT
  const txResponse = await signedTx.execute(client);
  const receipt = await txResponse.getReceipt(client);

  console.log("-----------------------------------");
  console.log(`✅ Reward of ${rewardAmount} ECO sent to ${collectorId}: ${receipt.status.toString()}`);
  console.log("-----------------------------------");

  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});