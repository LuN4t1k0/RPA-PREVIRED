const fs = require("fs");
const path = require("path");

const outputPath = path.resolve(__dirname, "..", "src", "config.generated.json");
const config = {
  appId: process.env.APP_ID || "previred-downloader"
};

fs.writeFileSync(outputPath, `${JSON.stringify(config, null, 2)}\n`);
console.log(`Config generada: ${outputPath}`);
