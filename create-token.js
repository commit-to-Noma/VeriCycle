/*
 - Purpose: Create the EcoCoin token on Hedera (demo token for VeriCycle).
 - Usage: run in an environment with `OPERATOR_ID` and `OPERATOR_KEY` set.
 - Output: prints the created token ID after success.
*/

import "dotenv/config";
import { Client, PrivateKey, TokenCreateTransaction, TokenSupplyType, TokenType } from "@hashgraph/sdk";

// Load operator keys from environment and validate
async function main() {
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;
  if (!operatorId || !operatorKey) throw new Error("OPERATOR_ID and OPERATOR_KEY must be set in .env");

  // Initialize Hedera client
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Connecting to Hedera and creating keys...");

  // Generate keys that will control token supply and administration
  const supplyKey = PrivateKey.generateECDSA();
  const adminKey = supplyKey;

  // Build token create transaction and freeze for signing
  const transaction = new TokenCreateTransaction()
    .setTokenName("EcoCoin")
    .setTokenSymbol("ECO")
    .setDecimals(2)
    .setInitialSupply(1_000_000_00)
    .setTokenType(TokenType.FUNGIBLE_COMMON)
    .setSupplyType(TokenSupplyType.Finite)
    .setMaxSupply(1_000_000_00)
    .setTreasuryAccountId(operatorId)
    .setAdminKey(adminKey.publicKey)
    .setSupplyKey(supplyKey.publicKey)
    .freezeWith(client);

  // Sign, execute and obtain receipt
  const signedTx = await transaction.sign(adminKey);
  const txResponse = await signedTx.execute(client);
  const receipt = await txResponse.getReceipt(client);
  const newTokenId = receipt.tokenId;

  console.log("-----------------------------------");
  console.log("✅ EcoCoin token created successfully!");
  console.log(`Your new Token ID is: ${newTokenId.toString()}`);
  console.log("-----------------------------------");

  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});