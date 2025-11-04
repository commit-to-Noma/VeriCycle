// This script sends your first EcoCoin reward!

import "dotenv/config";
import {
  Client,
  PrivateKey,
  TransferTransaction,
  AccountId, // Import AccountId
} from "@hashgraph/sdk";

async function main() {
  // 1. LOAD ALL YOUR SAVED KEYS AND IDs
  const operatorId = process.env.OPERATOR_ID; // This is the Treasury Account
  const operatorKey = PrivateKey.fromStringDer(process.env.OPERATOR_KEY); // Treasury's key
  
  const ecoCoinTokenId = process.env.ECOCOIN_TOKEN_ID;
  const collectorId = process.env.COLLECTOR_ID;

  if (!operatorId || !operatorKey || !ecoCoinTokenId || !collectorId) {
    throw new Error("Error: Please check your .env file. All variables must be set.");
  }
  
  // 2. SET UP YOUR HEDERA CLIENT
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  // This is the reward amount (e.g., 500 = 5.00 ECO)
  const rewardAmount = 500;

  console.log(`Connecting to Hedera and sending ${rewardAmount} ECO...`);

  // 3. BUILD THE TRANSACTION
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