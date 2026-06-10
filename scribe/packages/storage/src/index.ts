import {
  GetObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

// S3-compatible object storage (MinIO on Railway, Cloudflare R2, or AWS S3 —
// anything endpoint-configurable). The bucket is private; access is via
// signed URLs only (PRD §9). Prospected docs carry a 90-day lifecycle rule
// configured on the bucket itself. Path-style addressing is the default so
// MinIO works without wildcard DNS; set S3_FORCE_PATH_STYLE=0 if a provider
// requires virtual-hosted style.

let client: S3Client | null = null;

export function getS3(): S3Client {
  if (!client) {
    const endpoint = process.env.R2_ENDPOINT;
    if (!endpoint) throw new Error("R2_ENDPOINT is not set");
    client = new S3Client({
      region: process.env.R2_REGION ?? "auto",
      endpoint,
      forcePathStyle: process.env.S3_FORCE_PATH_STYLE !== "0",
      credentials: {
        accessKeyId: process.env.R2_ACCESS_KEY_ID ?? "",
        secretAccessKey: process.env.R2_SECRET_ACCESS_KEY ?? "",
      },
    });
  }
  return client;
}

export function bucket(): string {
  return process.env.R2_BUCKET ?? "scribe";
}

export async function putObject(
  key: string,
  body: Buffer | Uint8Array | string,
  contentType: string
): Promise<void> {
  await getS3().send(
    new PutObjectCommand({
      Bucket: bucket(),
      Key: key,
      Body: body,
      ContentType: contentType,
    })
  );
}

export async function getObject(key: string): Promise<Buffer> {
  const res = await getS3().send(
    new GetObjectCommand({ Bucket: bucket(), Key: key })
  );
  const bytes = await res.Body!.transformToByteArray();
  return Buffer.from(bytes);
}

export async function signedGetUrl(
  key: string,
  expiresInSeconds = 900
): Promise<string> {
  return getSignedUrl(
    getS3(),
    new GetObjectCommand({ Bucket: bucket(), Key: key }),
    { expiresIn: expiresInSeconds }
  );
}
