// This imports the 'dotenv' library to load our secret keys from .env
import "dotenv/config";

// These are the Hedera tools we need
import {
  Client,
  PrivateKey,
  TokenCreateTransaction,
  TokenSupplyType,
  TokenType, // <-- Make sure to import TokenType
} from "@hashgraph/sdk";

// This is the main function that will run
async function main() {
  
  // 1. LOAD YOUR KEYS
  // Get your Hedera account ID and private key from the .env file
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;

  // If we can't find them, stop the script
  if (!operatorId || !operatorKey) {
    throw new Error(
      "Error: OPERATOR_ID and OPERATOR_KEY must be set in your .env file."
    );
  }

  // 2. SET UP YOUR HEDERA CLIENT
  // This is how you connect to the Hedera test network
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Connecting to Hedera and creating keys...");

  // 3. GENERATE TOKEN KEYS
  // These keys will control your new token
  const supplyKey = PrivateKey.generateECDSA();
  const adminKey = supplyKey;

  // 4. BUILD THE TOKEN
  // This is the code from our snippet, customized for VeriCycle
  const transaction = new TokenCreateTransaction()
    .setTokenName("EcoCoin")
    .setTokenSymbol("ECO")
    .setDecimals(2) // 100 units = 1.00 ECO
    .setInitialSupply(1_000_000_00) // 1 Million tokens (1000000.00)
    .setTokenType(TokenType.FUNGIBLE_COMMON) // Set the token type
    .setSupplyType(TokenSupplyType.Finite)
    .setMaxSupply(1_000_000_00)
    .setTreasuryAccountId(operatorId) // Your account is the treasury
    .setAdminKey(adminKey.publicKey)
    .setSupplyKey(supplyKey.publicKey)
    .freezeWith(client);

  // 5. SIGN & EXECUTE
  // Sign the transaction with the admin key...
  const signedTx = await transaction.sign(adminKey);
  //...and execute it
  const txResponse = await signedTx.execute(client);
  // Get the receipt
  const receipt = await txResponse.getReceipt(client);

  // 6. GET THE NEW TOKEN ID
  const newTokenId = receipt.tokenId;

  console.log("-----------------------------------");
  console.log("✅ EcoCoin token created successfully!");
  console.log(`Your new Token ID is: ${newTokenId.toString()}`);
  console.log("-----------------------------------");

  client.close();
}

// This line runs the 'main' function
main().catch((error) => {
  console.error(error);
  process.exit(1);
});