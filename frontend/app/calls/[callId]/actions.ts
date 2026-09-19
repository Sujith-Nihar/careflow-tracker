"use server";

import { revalidatePath } from "next/cache";
import { completeCallback } from "@/lib/api";

/**
 * Record that a human dealt with the callback.
 *
 * Staff identity is a free-text field here because this exercise has no
 * authentication. In production this would come from the signed-in user, and the
 * audit row would be worth something.
 */
export async function markCallbackCompleted(formData: FormData) {
  const callId = String(formData.get("callId"));
  const callbackId = String(formData.get("callbackId"));
  const actor = String(formData.get("actor") || "front-desk");
  await completeCallback(callId, callbackId, actor);
  revalidatePath(`/calls/${callId}`);
  revalidatePath("/calls");
}
