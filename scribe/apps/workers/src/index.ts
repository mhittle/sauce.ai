import { Worker, Queue } from "bullmq";
import pino from "pino";
import { processTakeoff } from "./takeoff/process.js";
import { runSource, runAllSources } from "./crawler/run.js";
import { redisConnection } from "./lib/redis.js";

const log = pino({ level: process.env.LOG_LEVEL ?? "info" });

const connection = redisConnection();

const TAKEOFF_QUEUE = "takeoff.process";
const CRAWLER_QUEUE = "crawler.run";

const takeoffWorker = new Worker(
  TAKEOFF_QUEUE,
  async (job) => {
    log.info({ job: job.name, takeoff: job.data.takeoff_id }, "takeoff job start");
    await processTakeoff(job.data.takeoff_id, log);
  },
  { connection, concurrency: 2 }
);

const crawlerWorker = new Worker(
  CRAWLER_QUEUE,
  async (job) => {
    if (job.name === "crawl-all") {
      await runAllSources(log);
    } else if (job.name === "run-source") {
      await runSource(job.data.source_id, log);
    }
  },
  { connection, concurrency: 1 }
);

for (const w of [takeoffWorker, crawlerWorker]) {
  w.on("failed", (job, err) => {
    log.error({ job: job?.name, id: job?.id, err: err.message }, "job failed");
  });
}

// Default crawl cadence: every 6h per source (PRD §5.4).
const crawlerQueue = new Queue(CRAWLER_QUEUE, { connection });
await crawlerQueue.upsertJobScheduler(
  "crawl-all-every-6h",
  { every: 6 * 60 * 60 * 1000 },
  { name: "crawl-all" }
);

log.info("scribe workers up: takeoff + crawler");

async function shutdown() {
  await takeoffWorker.close();
  await crawlerWorker.close();
  await crawlerQueue.close();
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
