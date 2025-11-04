// This file is a TEMPLATE. We can't run it yet, but it's ready.

import "dotenv/config";
import {
  Client,
  PrivateKey,
  TokenAssociateTransaction,
} from "@hashgraph/sdk";

// This is the main function
async function main() {
  
  // --- !! THIS IS EXAMPLE DATA. WE WILL REPLACE THIS LATER. !! ---
  const collectorAccountId = "0.0.YOUR_COLLECTOR_ID";
  const collectorPrivateKey = PrivateKey.fromString("302e020100300... (the collector's key)");
  
  // This is your new, REAL EcoCoin ID!
  const ecoCoinTokenId = "0.0.7189125"; 
  // --- !! -------------------------------------------------- !! ---


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

  console.log("Associating a new collector with EcoCoin...");

  // 3. BUILD THE TRANSACTION
  const transaction = await new TokenAssociateTransaction()
    .setAccountId(collectorAccountId)
    .setTokenIds([ecoCoinTokenId])
    .freezeWith(client);

  // 4. SIGN WITH THE COLLECTOR'S KEY
  // The collector MUST sign to give permission
  const signedTx = await transaction.sign(collectorPrivateKey);

  // 5. SUBMIT & GET RECEIPT
  const txResponse = await signedTx.execute(client);
  const receipt = await txResponse.getReceipt(client);

  console.log(`✅ Collector ${collectorAccountId} associated with EcoCoin: ${receipt.status.toString()}`);

  client.close();
}

// This line runs the 'main' function
main().catch((error) => {
  console.error(error);
  process.exit(1);
});