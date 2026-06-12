// Standalone compile of EIVValidationRegistry with solc-js (no Hardhat needed).
// Outputs artifacts/EIVValidationRegistry.json with {abi, bytecode}.
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const source = fs.readFileSync(path.join(__dirname, "EIVValidationRegistry.sol"), "utf8");

const input = {
  language: "Solidity",
  sources: { "EIVValidationRegistry.sol": { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const out = JSON.parse(solc.compile(JSON.stringify(input)));
const errors = (out.errors || []).filter((e) => e.severity === "error");
if (errors.length) {
  for (const e of errors) console.error(e.formattedMessage);
  process.exit(1);
}

const c = out.contracts["EIVValidationRegistry.sol"]["EIVValidationRegistry"];
fs.mkdirSync(path.join(__dirname, "artifacts"), { recursive: true });
fs.writeFileSync(
  path.join(__dirname, "artifacts", "EIVValidationRegistry.json"),
  JSON.stringify({ abi: c.abi, bytecode: "0x" + c.evm.bytecode.object }, null, 2)
);
console.log("compiled: artifacts/EIVValidationRegistry.json");
console.log("bytecode bytes:", c.evm.bytecode.object.length / 2);
