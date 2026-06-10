import {
  GetObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

// R2 (S3-compatible) object storage. The bucket is private; access is via
// signed URLs only (PRD §9). Prospected docs carry a 90-day lifecycle rule
// configured on the bucket itself.

let client: S3Client | null = null;

export function getS3(): S3Client {
  if (!client) {
    const endpoint = process.env.R2_ENDPOINT;
    if (!endpoint) throw new Error("R2_ENDPOINT is not set");
    client = new S3Client({
      region: "auto",
      endpoint,
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
