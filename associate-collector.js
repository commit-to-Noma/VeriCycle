// This script will associate your new collector with your EcoCoin

import "dotenv/config";
import {
  Client,
  PrivateKey,
  TokenAssociateTransaction,
  AccountId, // Import AccountId
} from "@hashgraph/sdk";

async function main() {
  // 1. LOAD ALL YOUR SAVED KEYS AND IDs
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;

  const ecoCoinTokenId = process.env.ECOCOIN_TOKEN_ID;
  
  const collectorId = process.env.COLLECTOR_ID;
  // We MUST convert the string key from .env back into a PrivateKey object
  const collectorPrivateKey = PrivateKey.fromStringDer(process.env.COLLECTOR_KEY);

  if (!operatorId || !operatorKey || !ecoCoinTokenId || !collectorId || !collectorPrivateKey) {
    throw new Error("Error: Please check your .env file. All variables must be set.");
  }

  // 2. SET UP YOUR HEDERA CLIENT (pays for the transaction)
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Connecting to Hedera and associating collector...");

  // 3. BUILD THE TRANSACTION
  const transaction = await new TokenAssociateTransaction()
    .setAccountId(collectorId)
    .setTokenIds([ecoCoinTokenId])
    .freezeWith(client);

  // 4. SIGN WITH THE COLLECTOR'S KEY (to give permission)
  const signedTx = await transaction.sign(collectorPrivateKey);

  // 5. SUBMIT & GET RECEIPT
  const txResponse = await signedTx.execute(client);
  const receipt = await txResponse.getReceipt(client);

  console.log("-----------------------------------");
  console.log(`✅ Collector ${collectorId} associated with EcoCoin: ${receipt.status.toString()}`);
  console.log("-----------------------------------");

  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});