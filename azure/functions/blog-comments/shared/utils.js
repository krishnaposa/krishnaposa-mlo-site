const crypto = require("crypto");
const { v4: uuidv4 } = require("uuid");

const MAX_NAME = 60;
const MAX_EMAIL = 120;
const MAX_MESSAGE = 2000;

function sanitizeStr(s) { return String(s || "").trim(); }

function validateInput({ name, email, message }) {
    const n = sanitizeStr(name);
    const e = sanitizeStr(email);
    const m = sanitizeStr(message);
    if (!n || !m) return "Name and message are required.";
    if (n.length > MAX_NAME) return "Name too long.";
    if (e && e.length > MAX_EMAIL) return "Email too long.";
    if (m.length > MAX_MESSAGE) return "Message too long.";
    return null;
}

function hashIP(ip) {
    return crypto.createHash("sha256").update(ip || "").digest("hex").slice(0, 32);
}

function uuid() { return uuidv4(); }

function getClientIP(req) {
    return req.headers["x-forwarded-for"]?.split(",")[0]?.trim()
        || req.headers["x-client-ip"]
        || req.socket?.remoteAddress
        || "";
}

function escapeHtml(text) {
    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll("\"", "&quot;");
}

module.exports = { sanitizeStr, validateInput, hashIP, uuid, getClientIP, escapeHtml };