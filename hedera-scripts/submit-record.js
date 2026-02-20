#!/usr/bin/env node
// Demo stub for Hedera submission script
// Usage: node submit-record.js <operatorId> <operatorKey>
// Prints a mock transaction ID to stdout and exits 0.

const operatorId = process.argv[2] || '';
const operatorKey = process.argv[3] || '';

function randomInt(max) {
  return Math.floor(Math.random() * Math.floor(max));
}

const nowMs = Date.now();
const seconds = Math.floor(nowMs / 1000);
const nanos = (nowMs % 1000) * 1000000;
const txId = `0.0.${randomInt(1000000)}@${seconds}.${nanos}`;
console.log(`TX_ID=${txId}`);
process.exit(0);
