"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { estimatePoolWindow, estimateBatch } = require("../simulator/index.js");

const scenario = {dataset: {poolCapital: "20000", participantBps: "5000"}};

test("pool reference window", () => {
  assert.deepEqual(estimatePoolWindow(240, 500, scenario), {participantBudget: 120, marginShare: 3});
});

test("pool loss window", () => {
  assert.deepEqual(estimatePoolWindow(-240, 500, scenario), {participantBudget: 0, marginShare: 0});
});

test("upper margin scenario", () => {
  assert.deepEqual(estimatePoolWindow(600, 500, scenario), {participantBudget: 300, marginShare: 7.5});
});

test("accepted tasks drive receipts, every task incurs costs", () => {
  assert.deepEqual(estimateBatch(100, 80, 500, 180, 12000), {
    receipts: 40000, costs: 30000, margin: 10000, breakEven: 60,
  });
});

test("unpaid window still incurs costs", () => {
  assert.deepEqual(estimateBatch(10, 0, 500, 180, 0), {
    receipts: 0, costs: 1800, margin: -1800, breakEven: 4,
  });
});

test("zero unit price cannot cover expenses", () => {
  assert.equal(estimateBatch(10, 5, 0, 100, 0).breakEven, Infinity);
});
