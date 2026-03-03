#!/usr/bin/env node
import "dotenv/config";
import {
  Client,
  TopicMessageSubmitTransaction,
  Hbar,
} from "@hashgraph/sdk";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function submitOnce(operatorId, operatorKey, topicId, payload) {
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);
  const maxAttempts = Number(process.env.HEDERA_MAX_ATTEMPTS || 5);
  client.setMaxAttempts(Number.isFinite(maxAttempts) && maxAttempts > 0 ? maxAttempts : 5);
  if (typeof client.setRequestTimeout === "function") {
    client.setRequestTimeout(15000);
  }

  const tx = new TopicMessageSubmitTransaction({
    topicId,
    message: JSON.stringify(payload),
  })
    .setMaxTransactionFee(new Hbar(2))
    .setTransactionValidDuration(120);

  try {
    const response = await tx.execute(client);
    await response.getReceipt(client);
    return response.transactionId.toString();
  } finally {
    client.close();
  }
}

async function main() {
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;
  const topicId = process.env.VERICYCLE_TOPIC_ID;
  const activityId = process.argv[2] || "";
  const proofHash = process.argv[3] || "";

  if (!operatorId || !operatorKey || !topicId) {
    throw new Error("Missing OPERATOR_ID, OPERATOR_KEY, or VERICYCLE_TOPIC_ID in .env");
  }

  const payload = {
    activityId,
    proofHash,
    timestamp: new Date().toISOString(),
    verified: true,
  };

  let lastError = null;
  const maxTries = 8;
  for (let attempt = 1; attempt <= maxTries; attempt += 1) {
    try {
      const txId = await submitOnce(operatorId, operatorKey, topicId, payload);
      console.log(`TX_ID=${txId}`);
      return;
    } catch (error) {
      lastError = error;
      console.error(`WARN=submit attempt ${attempt} failed: ${error?.message || String(error)}`);
      if (attempt === maxTries) {
        break;
      }
      await sleep(400 * attempt);
    }
  }

  throw lastError || new Error("Unknown submit failure");
}

main().catch((error) => {
  console.error(`ERROR=${error?.message || String(error)}`);
  process.exit(1);
});
