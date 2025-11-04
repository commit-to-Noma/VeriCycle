// This script creates your HCS Logbook (Topic) ONE TIME.

import "dotenv/config";
import { Client, TopicCreateTransaction } from "@hashgraph/sdk";

async function main() {
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;

  if (!operatorId || !operatorKey) {
    throw new Error("Error: OPERATOR_ID and OPERATOR_KEY must be set.");
  }

  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Connecting to Hedera and creating the VeriCycle logbook...");

  const transaction = new TopicCreateTransaction();
  const txResponse = await transaction.execute(client);
  const receipt = await txResponse.getReceipt(client);
  
  const newTopicId = receipt.topicId;

  console.log("-----------------------------------");
  console.log(`✅ VeriCycle Logbook (Topic) created: ${newTopicId.toString()}`);
  console.log("!! IMPORTANT: Copy this Topic ID into your .env file NOW !!");
  console.log("-----------------------------------");

  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});