import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  storageState: 'e2e/.auth/admin.json'
});
const page = await context.newPage();

await page.goto('https://merchant.migaozn.com/products', { waitUntil: 'networkidle', timeout: 30000 });

// Click FAB
const fab = page.locator('button[title="打开米宝"]');
try {
  await fab.waitFor({ state: 'visible', timeout: 5000 });
  await fab.click();
  await page.waitForTimeout(2000);
} catch {
  console.log('FAB not found on /products');
}

await page.screenshot({ path: '/tmp/float-screenshot.png' });
console.log('Screenshot saved');

const panel = page.locator('[data-testid="chat-panel-resize-container"]');
const panelBox = await panel.boundingBox().catch(() => null);
if (panelBox) console.log(`Panel: ${panelBox.width}x${panelBox.height} at (${panelBox.x}, ${panelBox.y})`);
else console.log('Panel NOT FOUND');

const titleBar = page.locator('text=米宝').first();
const titleBox = await titleBar.boundingBox().catch(() => null);
if (titleBox) console.log(`Title: at (${titleBox.x}, ${titleBox.y})`);

const content = page.locator('[data-testid="chat-panel-content"]');
const contentBox = await content.boundingBox().catch(() => null);
if (contentBox) console.log(`Content: ${contentBox.width}x${contentBox.height} at (${contentBox.x}, ${contentBox.y})`);

const handle = page.locator('[data-testid="chat-panel-resize-handle"]');
const handleBox = await handle.boundingBox().catch(() => null);
if (handleBox) console.log(`Handle: at (${handleBox.x}, ${handleBox.y})`);

// Layout check
if (contentBox && handleBox) {
  const diff = handleBox.y - (contentBox.y + contentBox.height);
  console.log(`Handle below content by: ${diff.toFixed(0)}px`);
  if (Math.abs(diff) < 5) console.log('✅ Vertical layout correct');
  else console.log('❌ Layout issue: gap=' + diff.toFixed(0));
}
if (titleBox && contentBox) {
  console.log(`Title above content: ${titleBox.y < contentBox.y ? '✅' : '❌'}`);
}

await browser.close();
