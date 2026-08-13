import { Worker, Queue } from "bullmq";
import pino from "pino";
import {
  extractTakeoff,
  finalizeTakeoff,
  prepareTakeoff,
  processTakeoff,
} from "./takeoff/process.js";
import { detectRegion, renderBetaPage } from "./takeoff/detect.js";
import { runSource, runAllSources } from "./crawler/run.js";
import { redisConnection } from "./lib/redis.js";

const log = pino({ level: process.env.LOG_LEVEL ?? "info" });

const connection = redisConnection();

const TAKEOFF_QUEUE = "takeoff.process";
const CRAWLER_QUEUE = "crawler.run";

// Two-gate takeoff flow: `prepare` (thumbnails + classification →
// awaiting_pages), `extract` (read selected pages → awaiting_boxes),
// `finalize` (faces + pricing → review). The legacy `process` name still
// works — spreadsheets use it end-to-end, and in-flight jobs from before the
// split are routed into the gated flow by processTakeoff.
const takeoffWorker = new Worker(
  TAKEOFF_QUEUE,
  async (job) => {
    log.info({ job: job.name, takeoff: job.data.takeoff_id }, "takeoff job start");
    const id = job.data.takeoff_id;
    if (job.name === "prepare") await prepareTakeoff(id, log);
    else if (job.name === "extract") await extractTakeoff(id, log);
    else if (job.name === "finalize") await finalizeTakeoff(id, log);
    // Beta drag-to-detect jobs (no takeoff status transitions).
    else if (job.name === "beta_render")
      await renderBetaPage(id, job.data.page, log);
    else if (job.name === "detect")
      await detectRegion(job.data.detection_id, log);
    else await processTakeoff(id, log);
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
