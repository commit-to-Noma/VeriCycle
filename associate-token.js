import "dotenv/config";
import { Client, PrivateKey, TokenAssociateTransaction } from "@hashgraph/sdk";

const accountId = process.argv[2];
const accountKeyRaw = process.argv[3];
const tokenId = process.argv[4] || process.env.ECOCOIN_TOKEN_ID;

if (!accountId || !accountKeyRaw || !tokenId) {
  throw new Error("Usage: node associate-token.js <accountId> <accountPrivateKey> <tokenId>");
}

const operatorId = process.env.OPERATOR_ID;
const operatorKeyRaw = process.env.OPERATOR_KEY;
if (!operatorId || !operatorKeyRaw) {
  throw new Error("Missing OPERATOR_ID/OPERATOR_KEY in environment");
}

function parseKey(value) {
  try {
    return PrivateKey.fromString(value);
  } catch {
    return PrivateKey.fromStringDer(value);
  }
}

async function main() {
  const operatorKey = parseKey(operatorKeyRaw);
  const accountKey = parseKey(accountKeyRaw);

  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  const tx = await new TokenAssociateTransaction()
    .setAccountId(accountId)
    .setTokenIds([tokenId])
    .freezeWith(client);

  const signed = await tx.sign(accountKey);
  const submit = await signed.execute(client);
  const receipt = await submit.getReceipt(client);
  const txId = submit.transactionId?.toString?.() || "";

  console.log(`ASSOCIATE_STATUS=${receipt.status.toString()}`);
  if (txId) {
    console.log(`TX_ID=${txId}`);
  }

  client.close();
}

main().catch((error) => {
  console.error(`ERROR=${error?.message || String(error)}`);
  process.exit(1);
});
