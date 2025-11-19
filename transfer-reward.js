/*
 - Purpose: Send an EcoCoin reward to a collector via Hedera.
 - Usage: `node transfer-reward.js [COLLECTOR_ID] [AMOUNT]`
 - Requires: `.env` with `OPERATOR_ID`, `OPERATOR_KEY` (DER), and `ECOCOIN_TOKEN_ID`.
*/

import "dotenv/config";
import { Client, PrivateKey, TransferTransaction } from "@hashgraph/sdk";

// Parse command-line arguments: collector ID and amount
const collectorId = process.argv[2];
const rewardAmount = parseInt(process.argv[3]);
if (!collectorId || !rewardAmount) {
  throw new Error("Error: Missing Collector ID or Reward Amount. Usage: node transfer-reward.js [COLLECTOR_ID] [AMOUNT]");
}

// Load operator credentials and token id from environment
const operatorId = process.env.OPERATOR_ID;
const operatorKey = PrivateKey.fromStringDer(process.env.OPERATOR_KEY);
const ecoCoinTokenId = process.env.ECOCOIN_TOKEN_ID;
if (!operatorId || !operatorKey || !ecoCoinTokenId) {
  throw new Error("Error: Please check your .env file. All variables must be set.");
}

// Main: connect, build transfer, sign and submit
async function main() {
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log(`Connecting to Hedera and sending ${rewardAmount} ECO to ${collectorId}...`);

  const transaction = await new TransferTransaction()
    .addTokenTransfer(ecoCoinTokenId, operatorId, -rewardAmount)
    .addTokenTransfer(ecoCoinTokenId, collectorId, rewardAmount)
    .freezeWith(client);

  const signedTx = await transaction.sign(operatorKey);
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