import fs from "node:fs";
import path from "node:path";

const templatePath = process.env.TIPI_CONFIG_TEMPLATE ?? "/tipi-config/openclaw.json";
const targetPath = process.env.TIPI_CONFIG_TARGET ?? "/home/node/.openclaw/openclaw.json";

function merge(current, managed) {
  if (Array.isArray(managed)) return managed;
  if (managed && typeof managed === "object") {
    const result = current && typeof current === "object" && !Array.isArray(current) ? { ...current } : {};
    for (const [key, value] of Object.entries(managed)) result[key] = merge(result[key], value);
    return result;
  }
  return managed;
}

const managed = JSON.parse(fs.readFileSync(templatePath, "utf8"));
const openaiRealtime = managed?.talk?.realtime?.providers?.openai;
if (openaiRealtime) {
  const overrides = {
    noiseReductionType: process.env.TIPI_REALTIME_NOISE_REDUCTION,
    transcriptionLanguage: process.env.TIPI_REALTIME_TRANSCRIPTION_LANGUAGE,
    transcriptionPrompt: process.env.TIPI_REALTIME_TRANSCRIPTION_PROMPT,
  };
  for (const [key, value] of Object.entries(overrides)) {
    if (value?.trim()) openaiRealtime[key] = value.trim();
  }
}
let current = {};
try {
  current = JSON.parse(fs.readFileSync(targetPath, "utf8"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}
const updated = `${JSON.stringify(merge(current, managed), null, 2)}\n`;
const previous = fs.existsSync(targetPath) ? fs.readFileSync(targetPath, "utf8") : "";
if (updated !== previous) {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  const temporary = `${targetPath}.tipi.tmp`;
  fs.writeFileSync(temporary, updated, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, targetPath);
  console.log("Configuración administrada de Tipi actualizada.");
}
