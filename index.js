#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { setTimeout: delay } = require("node:timers/promises");

const DEFAULT_INPUT_FILE = "users.txt";
const UNIVERSAL_DATA_SCRIPT_ID = "__UNIVERSAL_DATA_FOR_REHYDRATION__";
const NUMBER_FORMAT = new Intl.NumberFormat("vi-VN");
const REQUEST_HEADERS = {
  "accept-language": "en-US,en;q=0.9",
  "cache-control": "no-cache",
  pragma: "no-cache",
  referer: "https://www.tiktok.com/",
  "user-agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
};

function printHelp() {
  console.log(`
TikTok follow checker

Usage:
  node index.js username
  node index.js "@username"
  node index.js user1 user2 user3
  node index.js --file users.example.txt
  node index.js --json username

Input format:
  - @username
  - username
  - https://www.tiktok.com/@username

Options:
  --file <path>    Read usernames from a text file, one username per line
  --json           Print JSON instead of a console table
  --help           Show this help message

Tip:
  If you do not pass usernames and a ${DEFAULT_INPUT_FILE} file exists, the tool
  will read from that file automatically.

PowerShell note:
  If you want to pass @username directly, wrap it in quotes: "@username"
`.trim());
}

function parseArgs(argv) {
  const options = {
    json: false,
    file: null,
    inputs: [],
  };

  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];

    if (current === "--help" || current === "-h") {
      options.help = true;
      continue;
    }

    if (current === "--json") {
      options.json = true;
      continue;
    }

    if (current === "--file") {
      const nextValue = argv[index + 1];
      if (!nextValue) {
        throw new Error("Missing value for --file");
      }
      options.file = nextValue;
      index += 1;
      continue;
    }

    options.inputs.push(current);
  }

  return options;
}

function readUsersFromFile(filePath) {
  const absolutePath = path.resolve(filePath);
  const content = fs.readFileSync(absolutePath, "utf8");

  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

function normalizeUsername(rawValue) {
  if (!rawValue) {
    throw new Error("Empty username");
  }

  const value = rawValue.trim();
  if (!value) {
    throw new Error("Empty username");
  }

  if (/^https?:\/\//i.test(value)) {
    let parsedUrl;
    try {
      parsedUrl = new URL(value);
    } catch (error) {
      throw new Error(`Invalid TikTok URL: ${value}`);
    }

    const segments = parsedUrl.pathname.split("/").filter(Boolean);
    const accountSegment = segments.find((segment) => segment.startsWith("@"));
    if (!accountSegment) {
      throw new Error(`Could not find TikTok username in URL: ${value}`);
    }

    return accountSegment.slice(1);
  }

  return value.replace(/^@/, "");
}

function extractJsonFromHtml(html, scriptId) {
  const pattern = new RegExp(
    `<script[^>]*id="${scriptId}"[^>]*>([\\s\\S]*?)<\\/script>`,
    "i",
  );
  const match = html.match(pattern);

  if (!match) {
    throw new Error(`Could not find script tag: ${scriptId}`);
  }

  return match[1];
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatNumber(value) {
  return value === null || value === undefined ? "-" : NUMBER_FORMAT.format(value);
}

async function fetchProfileStats(username) {
  const profileUrl = `https://www.tiktok.com/@${encodeURIComponent(username)}?lang=en`;
  const response = await fetch(profileUrl, {
    headers: REQUEST_HEADERS,
    redirect: "follow",
  });

  const html = await response.text();
  const embeddedJson = extractJsonFromHtml(html, UNIVERSAL_DATA_SCRIPT_ID);

  let parsedData;
  try {
    parsedData = JSON.parse(embeddedJson);
  } catch (error) {
    throw new Error("Could not parse TikTok embedded profile data");
  }

  const detail =
    parsedData.__DEFAULT_SCOPE__ &&
    parsedData.__DEFAULT_SCOPE__["webapp.user-detail"];

  if (!detail) {
    throw new Error("TikTok profile payload was missing user detail data");
  }

  const userInfo = detail.userInfo || {};
  const user = userInfo.user || {};
  const stats = userInfo.statsV2 || userInfo.stats;

  if (!stats) {
    const message = detail.statusMsg || `HTTP ${response.status}`;
    throw new Error(message);
  }

  return {
    input: username,
    uniqueId: user.uniqueId || username,
    nickname: user.nickname || "",
    followers: toNumber(stats.followerCount),
    following: toNumber(stats.followingCount),
    likes: toNumber(stats.heartCount ?? stats.heart),
    videos: toNumber(stats.videoCount),
    verified: Boolean(user.verified),
    privateAccount: Boolean(user.privateAccount),
    statusCode: detail.statusCode,
    statusMsg: detail.statusMsg || "OK",
    profileUrl: `https://www.tiktok.com/@${user.uniqueId || username}`,
  };
}

function shouldRetry(error) {
  const message = String(error && error.message ? error.message : error);
  return (
    message.includes("Could not find script tag") ||
    message.includes("Could not parse TikTok embedded profile data") ||
    message.includes("fetch failed") ||
    message.includes("HTTP 429")
  );
}

async function fetchProfileStatsWithRetry(username, maxAttempts = 3) {
  let lastError;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await fetchProfileStats(username);
    } catch (error) {
      lastError = error;

      if (attempt === maxAttempts || !shouldRetry(error)) {
        throw error;
      }

      await delay(500 * attempt);
    }
  }

  throw lastError;
}

async function collectStats(usernames) {
  const results = [];

  for (const username of usernames) {
    try {
      const stats = await fetchProfileStatsWithRetry(username);
      results.push({
        ok: true,
        ...stats,
      });
    } catch (error) {
      results.push({
        ok: false,
        input: username,
        uniqueId: username,
        nickname: "",
        followers: null,
        following: null,
        likes: null,
        videos: null,
        verified: false,
        privateAccount: false,
        statusCode: null,
        statusMsg: error.message,
        profileUrl: `https://www.tiktok.com/@${username}`,
      });
    }
  }

  return results;
}

function printTable(results) {
  const rows = results.map((result) => ({
    username: result.uniqueId,
    nickname: result.nickname,
    followers: formatNumber(result.followers),
    following: formatNumber(result.following),
    likes: formatNumber(result.likes),
    videos: formatNumber(result.videos),
    private: result.privateAccount ? "yes" : "no",
    verified: result.verified ? "yes" : "no",
    status: result.ok ? "ok" : result.statusMsg,
  }));

  console.table(rows);
}

async function main() {
  const options = parseArgs(process.argv.slice(2));

  if (options.help) {
    printHelp();
    return;
  }

  let rawInputs = [...options.inputs];

  if (options.file) {
    rawInputs = rawInputs.concat(readUsersFromFile(options.file));
  }

  if (!rawInputs.length && fs.existsSync(path.resolve(DEFAULT_INPUT_FILE))) {
    rawInputs = readUsersFromFile(DEFAULT_INPUT_FILE);
  }

  if (!rawInputs.length) {
    printHelp();
    process.exitCode = 1;
    return;
  }

  const usernames = [...new Set(rawInputs.map(normalizeUsername))];
  const results = await collectStats(usernames);

  if (options.json) {
    console.log(JSON.stringify(results, null, 2));
    return;
  }

  printTable(results);
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});
