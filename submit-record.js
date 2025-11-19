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

  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Submitting new record to the VeriCycle Logbook...");

  const message = JSON.stringify(dropOffData);
  const transaction = new TopicMessageSubmitTransaction({ topicId: logbookTopicId, message });
  const txResponse = await transaction.execute(client);
  const receipt = await txResponse.getReceipt(client);

  console.log(`✅ New verification record submitted: ${receipt.status.toString()}`);
  client.close();
  return receipt.status.toString();
}

export { submitRecord };