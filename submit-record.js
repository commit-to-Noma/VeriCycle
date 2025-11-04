// This is the TEMPLATE for submitting a verification record.

import "dotenv/config";
import { Client, TopicMessageSubmitTransaction } from "@hashgraph/sdk";

// This is the main function your Flask app will call
async function submitRecord(dropOffData) {
  
  // Example dropOffData:
  // {
  //   centerId: "0.0.11223",
  //   centerName: "Pikitup Marlboro",
  //   collectorId: "0.0.44556",
  //   collectorName: "Nomathemba Ncube",
  //   material: "Aluminum Cans",
  //   weightKg: 1.5,
  //   rewardEcoCoin": 75,
  //   timestamp": "2025-11-12T14:35:01Z"
  // }
  
  // 1. LOAD YOUR KEYS AND IDs
  const operatorId = process.env.OPERATOR_ID;
  const operatorKey = process.env.OPERATOR_KEY;
  const logbookTopicId = process.env.VERICYCLE_TOPIC_ID;
  
  if (!operatorId || !operatorKey || !logbookTopicId) {
    throw new Error("Error: Please check your .env file. All variables must be set.");
  }

  // 2. SET UP YOUR HEDERA CLIENT
  const client = Client.forTestnet();
  client.setOperator(operatorId, operatorKey);

  console.log("Submitting new record to the VeriCycle Logbook...");

  // 3. CONVERT YOUR DATA TO A STRING
  const message = JSON.stringify(dropOffData);

  // 4. BUILD AND EXECUTE THE TRANSACTION
  const transaction = new TopicMessageSubmitTransaction({
    topicId: logbookTopicId,
    message: message,
  });
  
  const txResponse = await transaction.execute(client);
  const receipt = await txResponse.getReceipt(client);

  console.log(`✅ New verification record submitted: ${receipt.status.toString()}`);
  
  client.close();

  return receipt.status.toString();
}

// We don't run this file directly, so we just export the function
export { submitRecord };