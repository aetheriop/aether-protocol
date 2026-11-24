"use strict";

// The window uses settled margin after expenses and reserves.
function estimatePoolWindow(netMargin, contribution, scenario) {
  const participantBudget = Math.max(0, netMargin) * Number(scenario.dataset.participantBps) / 10000;
  const marginShare = participantBudget * contribution / Number(scenario.dataset.poolCapital);
  return { participantBudget, marginShare };
}

function estimateBatch(volume, accepted, price, unitCost, overhead) {
  // All money inputs and results are in integer cents.
  const receipts = accepted * price;
  const costs = volume * unitCost + overhead;
  const margin = receipts - costs;
  const breakEven = price > 0 ? Math.ceil(costs / price) : costs === 0 ? 0 : Infinity;
  return { receipts, costs, margin, breakEven };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { estimatePoolWindow, estimateBatch };
}
