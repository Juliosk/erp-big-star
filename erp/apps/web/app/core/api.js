// Cliente da API: token só em memória, If-Match (versão) e Idempotency-Key.
import { ERRORS } from "./errors.js";

let token = "";
let onUnauthorized = () => {};

export const setToken = (value) => { token = value; };
export const clearToken = () => { token = ""; };
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };
export const newKey = () => crypto.randomUUID();

export async function api(path, { method = "GET", body, version, key } = {}) {
  const sentToken = token;
  const headers = { Authorization: `Bearer ${sentToken}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (version !== undefined) headers["If-Match"] = `"${version}"`;
  if (key) headers["Idempotency-Key"] = key;
  let response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      redirect: "error",
    });
  } catch {
    throw new Error("Não foi possível conectar. Verifique a aplicação e tente novamente.");
  }
  let result = null;
  try { result = await response.json(); } catch { /* resposta sem corpo */ }
  if (!response.ok) {
    if (response.status === 401 && sentToken === token) onUnauthorized();
    const code = result?.error?.code || "UNKNOWN";
    const trace = result?.error?.correlation_id;
    const text = ERRORS[code] || result?.error?.message || "Não foi possível concluir a operação.";
    const error = new Error(`${text}${trace ? ` Referência: ${trace}` : ""}`);
    error.code = code;
    error.status = response.status;
    throw error;
  }
  return result;
}
