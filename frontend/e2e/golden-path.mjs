import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";

const executablePath = process.env.BROWSER_EXECUTABLE_PATH
  ?? (process.platform === "win32"
    ? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
    : undefined);
const browser = await chromium.launch({
  executablePath,
  headless: true,
});

const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const goldenPath = [
  ["今天终于忙完了", "[rapport]"],
  ["周末想放松一下", "[weekend]"],
  ["你平时会出去玩吗", "[beach_trip]"],
  ["海边听起来不错，你去过哪", "[photo_offer]"],
  ["你当时拍照片了吗", "[photo_offer]"],
  ["给我看看", "[photo_sent]"],
];

try {
  await mkdir("e2e/artifacts", { recursive: true });
  await page.goto(`${baseUrl}/#/chat`, { waitUntil: "networkidle" });

  const input = page.getByPlaceholder("输入消息…");
  await input.waitFor({ state: "visible" });
  await page.getByText("林小满", { exact: true }).waitFor();

  for (const [message, marker] of goldenPath) {
    await input.fill(message);
    await page.getByRole("button", { name: "发送" }).click();
    await page.getByText(new RegExp(`^\\${marker}`)).last().waitFor({ timeout: 10_000 });
    await page.getByRole("button", { name: "发送" }).waitFor({ state: "visible" });
  }

  const beachPhoto = page.getByAltText("角色发送的剧情图片").last();
  await beachPhoto.waitFor();
  const beachSrc = await beachPhoto.getAttribute("src");
  if (!beachSrc?.endsWith("/static/assets/beach_photo.svg")) {
    throw new Error(`unexpected final image src: ${beachSrc}`);
  }

  const conversationId = await page.evaluate(() => localStorage.getItem("personaflow.conversation_id"));
  if (!conversationId) throw new Error("conversation id was not persisted");

  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("给我看看", { exact: true }).waitFor();
  await page.getByAltText("角色发送的剧情图片").last().waitFor();
  await page.screenshot({ path: "e2e/artifacts/chat-golden-path.png", fullPage: true });

  await page.getByRole("link", { name: "Admin" }).click();
  await page.getByRole("heading", { name: "Admin Debug" }).waitFor();
  await page.getByText("photo_sent", { exact: true }).first().waitFor();
  await page.getByText("TurnLog (6)", { exact: true }).waitFor();

  await page.screenshot({ path: "e2e/artifacts/admin-golden-path.png", fullPage: true });
  console.log(JSON.stringify({
    ok: true,
    conversationId,
    finalNode: "photo_sent",
    finalAsset: beachSrc,
    turnLogs: 6,
    refreshHistory: true,
  }));
} finally {
  await browser.close();
}
