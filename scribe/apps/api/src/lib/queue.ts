import { Queue, type ConnectionOptions } from "bullmq";

function redisConnection(): ConnectionOptions {
  const url = new URL(process.env.REDIS_URL ?? "redis://localhost:6379");
  return {
    host: url.hostname,
    port: Number(url.port || 6379),
    username: url.username || undefined,
    password: url.password || undefined,
    ...(url.protocol === "rediss:" ? { tls: {} } : {}),
    maxRetriesPerRequest: null,
  };
}

export const TAKEOFF_QUEUE = "takeoff.process";
export const CRAWLER_QUEUE = "crawler.run";

let takeoffQueue: Queue | null = null;
let crawlerQueue: Queue | null = null;

export function getTakeoffQueue(): Queue {
  if (!takeoffQueue) {
    takeoffQueue = new Queue(TAKEOFF_QUEUE, { connection: redisConnection() });
  }
  return takeoffQueue;
}

export function getCrawlerQueue(): Queue {
  if (!crawlerQueue) {
    crawlerQueue = new Queue(CRAWLER_QUEUE, { connection: redisConnection() });
  }
  return crawlerQueue;
}
