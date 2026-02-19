/*
 - Purpose: Submit a verification record to the VeriCycle Hedera logbook topic.
 - Usage: imported and called by the Flask backend with a `dropOffData` object.
 - Requires: `.env` containing `OPERATOR_ID`, `OPERATOR_KEY`, and `VERICYCLE_TOPIC_ID`.
*/

import "dotenv/config";
import { Client, TopicMessageSubmitTransaction } from "@hashgraph/sdk";

// Convert the drop-off data to a Hedera Topic message and submit it
async function submitRecord(dropOffData) {
  // Example `dropOffData` shape is documented in the codebase; keep payload small and JSON-serializable
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;
  const logbookTopicId = process.env.VERICYCLE_TOPIC_ID;
  if (!operatorId || !operatorKey || !logbookTopicId) throw new Error("Please set OPERATOR_ID, OPERATOR_KEY and VERICYCLE_TOPIC_ID in .env");

  // ===== DEBUG: Log which operator is being used (credentials are NOT printed) =====
  console.error(`[HEDERA] Using operator: ${operatorId}`);

  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.error("Submitting new record to the VeriCycle Logbook...");

  const message = JSON.stringify(dropOffData);
  const transaction = new TopicMessageSubmitTransaction({ topicId: logbookTopicId, message });
  const txResponse = await transaction.execute(client);
  const receipt = await txResponse.getReceipt(client);

  console.error(`✅ New verification record submitted: ${receipt.status.toString()}`);
  client.close();
  
  // Return transaction ID as the single source of truth
  return txResponse.transactionId.toString();
}

// CLI support: allow running as a standalone script
const cliMode = process.argv[1]?.endsWith('submit-record.js') && process.argv.length > 2;

if (cliMode) {
  const activityId = process.argv[2];
  const timestamp = new Date().toISOString();
  const dropOffData = { activityId, timestamp, verified: true };
  
  submitRecord(dropOffData)
    .then(txId => {
      console.log(`TX_ID=${txId}`);
      process.exit(0);
    })
    .catch(error => {
      console.error('Error:', error.message);
      process.exit(1);
    });
}

export { submitRecord };